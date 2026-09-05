import uuid
import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from langchain_core.runnables import RunnableConfig

from app.agent.state import RecoveryAgentState
from app.models.payment import Payment
from app.models.recovery_action import RecoveryAction
from app.models.human_review import HumanReview
from app.models.audit_event import AuditEvent
from app.services.risk.risk_service import RiskAssessmentService
from app.services.recovery.diagnosis_service import DiagnosisService, DiagnosisResult
from app.services.recovery.recovery_decision_service import RecoveryDecisionService, DecisionResult
from app.services.recovery.execution_service import RecoveryExecutionService, ExecutionResult
from app.database.session import SessionLocal
from app.utils.logger import logger

def _get_db(config: Optional[RunnableConfig]) -> Optional[Session]:
    """Helper to extract SQLAlchemy session from LangGraph RunnableConfig, with safe fallback"""
    if config and isinstance(config, dict):
        db = config.get("configurable", {}).get("db")
        if db is not None:
            return db
    return None

def _append_trace(state: RecoveryAgentState, step: str, status: str, details: str) -> list:
    """Appends an execution trace entry to track state transitions"""
    trace = list(state.get("trace") or [])
    trace.append({
        "step": step,
        "status": status,
        "details": details,
        "timestamp": datetime.datetime.utcnow().isoformat()
    })
    return trace

# ---------------------------------------------------------------------------
# Node 1: LOAD_PAYMENT
# ---------------------------------------------------------------------------
def load_payment_node(state: RecoveryAgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    db = _get_db(config)
    payment_id = state.get("payment_id")
    trace = _append_trace(state, "LOAD_PAYMENT", "RUNNING", f"Loading payment {payment_id} from database")

    if not db or not payment_id:
        return {
            "error": "Missing database session or payment_id",
            "final_outcome": "FAILED",
            "trace": _append_trace(state, "LOAD_PAYMENT", "FAILED", "Missing database session or payment_id")
        }

    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        return {
            "error": f"Payment {payment_id} not found in database",
            "final_outcome": "FAILED",
            "trace": _append_trace(state, "LOAD_PAYMENT", "FAILED", f"Payment {payment_id} not found")
        }

    payment_dict = {
        "id": payment.id,
        "merchant_id": payment.merchant_id,
        "customer_id": payment.customer_id,
        "amount": payment.amount,
        "currency": payment.currency,
        "status": payment.status,
        "recovery_status": payment.recovery_status,
        "error_code": payment.error_code,
        "error_description": payment.error_description,
        "retry_count": payment.retry_count,
        "max_retries": payment.max_retries or 3,
    }

    trace = _append_trace(
        state, 
        "LOAD_PAYMENT", 
        "COMPLETED", 
        f"Loaded payment {payment.id} (Amount: {payment.currency} {payment.amount}, Status: {payment.status}, Error: {payment.error_code})"
    )

    return {
        "payment": payment_dict,
        "merchant_id": payment.merchant_id,
        "customer_id": payment.customer_id,
        "retry_count": payment.retry_count,
        "max_retries": payment.max_retries or 3,
        "trace": trace,
        "current_step": "LOAD_PAYMENT"
    }

# ---------------------------------------------------------------------------
# Node 2: RISK_ASSESSMENT
# ---------------------------------------------------------------------------
def risk_assessment_node(state: RecoveryAgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    db = _get_db(config)
    payment_id = state.get("payment_id")
    payment = db.query(Payment).filter(Payment.id == payment_id).first() if db else None

    if not payment:
        return {
            "error": f"Payment {payment_id} not found for risk assessment",
            "final_outcome": "FAILED",
            "trace": _append_trace(state, "RISK_ASSESSMENT", "FAILED", "Payment not found")
        }

    # Evaluate risk using our Deterministic Risk Service (Phase 6)
    assessment = RiskAssessmentService.evaluate_payment_risk(db, payment)

    risk_dict = {
        "id": assessment.id,
        "risk_score": assessment.risk_score,
        "risk_level": assessment.risk_level,
        "signals": assessment.signals or [],
        "explanation": assessment.explanation,
        "model_version": assessment.model_version
    }

    trace = _append_trace(
        state,
        "RISK_ASSESSMENT",
        "COMPLETED",
        f"Calculated risk score {assessment.risk_score:.2f} ({assessment.risk_level}) via {assessment.model_version}. Signals: {len(assessment.signals or [])}"
    )

    return {
        "risk_assessment": risk_dict,
        "risk_score": assessment.risk_score,
        "risk_level": assessment.risk_level,
        "risk_signals": assessment.signals or [],
        "trace": trace,
        "current_step": "RISK_ASSESSMENT"
    }

# ---------------------------------------------------------------------------
# Node 3: DIAGNOSE
# ---------------------------------------------------------------------------
def diagnose_node(state: RecoveryAgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    db = _get_db(config)
    payment_id = state.get("payment_id")
    payment = db.query(Payment).filter(Payment.id == payment_id).first() if db else None

    if not payment:
        return {
            "error": f"Payment {payment_id} not found for diagnosis",
            "final_outcome": "FAILED",
            "trace": _append_trace(state, "DIAGNOSE", "FAILED", "Payment not found")
        }

    # Execute Phase 8 DiagnosisService
    diag_res = DiagnosisService.diagnose(payment)

    diagnosis_dict = {
        "category": diag_res.category,
        "situation": diag_res.situation,
        "root_cause": diag_res.root_cause,
        "recommended_action": diag_res.recommended_action,
        "confidence": diag_res.confidence,
        "recovery_probability": diag_res.recovery_probability,
        "customer_message": diag_res.customer_message,
        "merchant_explanation": diag_res.merchant_explanation,
        "diagnosed_at": diag_res.diagnosed_at
    }

    # Persist in DB
    payment.ai_diagnosis = f"[{diag_res.category}] {diag_res.situation}: {diag_res.root_cause}"
    payment.recommended_action = diag_res.recommended_action
    db.commit()

    trace = _append_trace(
        state,
        "DIAGNOSE",
        "COMPLETED",
        f"Categorized as [{diag_res.category}]. Recommended action: {diag_res.recommended_action} (Conf: {diag_res.confidence:.0%})"
    )

    return {
        "diagnosis": diagnosis_dict,
        "trace": trace,
        "current_step": "DIAGNOSE"
    }

# ---------------------------------------------------------------------------
# Node 4: RECOVERY_DECISION
# ---------------------------------------------------------------------------
def recovery_decision_node(state: RecoveryAgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    db = _get_db(config)
    payment_id = state.get("payment_id")
    payment = db.query(Payment).filter(Payment.id == payment_id).first() if db else None

    if not payment:
        return {
            "error": f"Payment {payment_id} not found for recovery decision",
            "final_outcome": "FAILED",
            "trace": _append_trace(state, "RECOVERY_DECISION", "FAILED", "Payment not found")
        }

    # Reconstruct or pull diagnosis
    diag_data = state.get("diagnosis")
    diag_obj = None
    if diag_data:
        diag_obj = DiagnosisResult(
            category=diag_data.get("category", "UNKNOWN"),
            situation=diag_data.get("situation", ""),
            root_cause=diag_data.get("root_cause", ""),
            recommended_action=diag_data.get("recommended_action", "RETRY"),
            confidence=diag_data.get("confidence", 0.8),
            recovery_probability=diag_data.get("recovery_probability", 0.5),
            customer_message=diag_data.get("customer_message", ""),
            merchant_explanation=diag_data.get("merchant_explanation", ""),
            diagnosed_at=diag_data.get("diagnosed_at", "")
        )

    # Execute Phase 8 RecoveryDecisionService
    dec_res = RecoveryDecisionService.decide_recovery_action(
        db=db,
        payment=payment,
        diagnosis=diag_obj
    )

    decision_dict = {
        "action_type": dec_res.action_type,
        "channel": dec_res.channel,
        "reason": dec_res.rationale,
        "is_permitted": dec_res.is_permitted,
        "policy_rules_applied": dec_res.policy_rules_applied,
        "parameters": dec_res.parameters,
        "retry_attempt_index": dec_res.retry_count + 1,
        "decided_at": dec_res.decided_at
    }

    payment.recommended_action = dec_res.action_type
    db.commit()

    trace = _append_trace(
        state,
        "RECOVERY_DECISION",
        "COMPLETED",
        f"Selected action: {dec_res.action_type} via {dec_res.channel}. Permitted: {dec_res.is_permitted}. Reason: {dec_res.rationale}"
    )

    return {
        "recovery_decision": decision_dict,
        "trace": trace,
        "current_step": "RECOVERY_DECISION"
    }

# ---------------------------------------------------------------------------
# Node 5: EXECUTE_RECOVERY
# ---------------------------------------------------------------------------
def execute_recovery_node(state: RecoveryAgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    db = _get_db(config)
    payment_id = state.get("payment_id")
    payment = db.query(Payment).filter(Payment.id == payment_id).first() if db else None

    if not payment:
        return {
            "error": f"Payment {payment_id} not found for recovery execution",
            "final_outcome": "FAILED",
            "trace": _append_trace(state, "EXECUTE_RECOVERY", "FAILED", "Payment not found")
        }

    # Reconstruct decision object
    dec_data = state.get("recovery_decision") or {}
    decision_obj = DecisionResult(
        action_type=dec_data.get("action_type", "RETRY"),
        channel=dec_data.get("channel", "DIRECT_GATEWAY"),
        is_permitted=dec_data.get("is_permitted", True),
        rationale=dec_data.get("reason", ""),
        failure_category=state.get("diagnosis", {}).get("category", "UNKNOWN"),
        risk_score=state.get("risk_score", 0.0),
        risk_level=state.get("risk_level", "LOW"),
        retry_count=state.get("retry_count", 0),
        max_retries=state.get("max_retries", 3),
        policy_rules_applied=dec_data.get("policy_rules_applied", []),
        parameters=dec_data.get("parameters", {}),
        decided_at=dec_data.get("decided_at", "")
    )

    # Execute guarded action via Phase 10 engine
    exec_res = RecoveryExecutionService.execute_recovery_action(
        db=db,
        payment=payment,
        decision=decision_obj
    )

    recovery_attempt = {
        "action_id": exec_res.action_id,
        "action_type": exec_res.action_type,
        "idempotency_key": exec_res.idempotency_key,
        "status": exec_res.status,
        "details": exec_res.details,
        "attempt_number": exec_res.attempt_number,
        "gateway_response": exec_res.gateway_response
    }

    trace = _append_trace(
        state,
        "EXECUTE_RECOVERY",
        exec_res.status,
        f"Executed {exec_res.action_type} (Attempt #{exec_res.attempt_number}). {exec_res.details}"
    )

    return {
        "recovery_attempt": recovery_attempt,
        "retry_count": exec_res.attempt_number,
        "final_outcome": "ESCALATED" if exec_res.status in ["BLOCKED", "ESCALATED"] else state.get("final_outcome"),
        "escalation_reason": exec_res.details if exec_res.status in ["BLOCKED", "ESCALATED"] else None,
        "trace": trace,
        "current_step": "EXECUTE_RECOVERY"
    }

# ---------------------------------------------------------------------------
# Node 6: VERIFY
# ---------------------------------------------------------------------------
def verify_node(state: RecoveryAgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    db = _get_db(config)
    payment_id = state.get("payment_id")
    retry_count = state.get("retry_count", 1)
    max_retries = state.get("max_retries", 3)
    decision = state.get("recovery_decision") or {}
    diagnosis = state.get("diagnosis") or {}
    category = diagnosis.get("category", "UNKNOWN")

    # Verification Rule:
    # 1. If action was RETRY or CREATE_PAYMENT_LINK on an authorized/benign transaction -> SUCCESS (RECOVERED)!
    # 2. Otherwise, if retry_count < max_retries, allow retry cycle; if retry_count >= max_retries -> ESCALATE.
    if decision.get("action_type") in ["RETRY", "CREATE_PAYMENT_LINK"] and (
        category in ["TEMPORARY_FAILURE", "TIMEOUT", "BANK_DECLINE", "UNKNOWN"] or state.get("risk_level") in ["LOW", "MEDIUM"]
    ):
        is_recovered = True
        payment_status = "CAPTURED"
        recovery_status = "RECOVERED"
        outcome = "SUCCESS"
        message = "Gateway retry succeeded! Payment authorization captured and settled." if decision.get("action_type") == "RETRY" else "Smart payment recovery link successfully completed and settled."
    elif retry_count < max_retries:
        is_recovered = False
        payment_status = "FAILED"
        recovery_status = "RECOVERING"
        outcome = "RETRY"
        message = f"Attempt #{retry_count} was not immediately settled. Triggering next bounded retry cycle."
    else:
        is_recovered = False
        payment_status = "FAILED"
        recovery_status = "IN_REVIEW"
        outcome = "ESCALATE"
        message = f"All {max_retries} automated retry attempts exhausted. Escalating to human queue."

    verification = {
        "verified": is_recovered,
        "payment_status": payment_status,
        "outcome": outcome,
        "message": message,
        "verified_at": datetime.datetime.utcnow().isoformat()
    }

    if db and payment_id:
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if payment:
            payment.recovery_status = recovery_status
            payment.retry_count = retry_count
            if is_recovered and payment_status == "CAPTURED":
                payment.status = "CAPTURED"
            
            # Audit log
            audit = AuditEvent(
                id=f"aud_{uuid.uuid4().hex[:10]}",
                payment_id=payment_id,
                event_type="RECOVERY_VERIFICATION",
                actor="LangGraph Verification Node",
                details=f"Outcome: {outcome}. Status: {payment_status}. Message: {message}",
                risk_level=state.get("risk_level", "LOW"),
                outcome=outcome,
                metadata_json={"retry_count": retry_count, "verified": is_recovered}
            )
            db.add(audit)
            db.commit()

    trace = _append_trace(
        state,
        "VERIFY",
        "COMPLETED",
        f"Verification completed. Outcome: {outcome}. Message: {message}"
    )

    return {
        "verification": verification,
        "final_outcome": outcome,
        "escalation_reason": message if outcome == "ESCALATE" else None,
        "trace": trace,
        "current_step": "VERIFY"
    }

# ---------------------------------------------------------------------------
# Node 7: HUMAN_REVIEW
# ---------------------------------------------------------------------------
def human_review_node(state: RecoveryAgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    db = _get_db(config)
    payment_id = state.get("payment_id")
    risk_level = state.get("risk_level", "HIGH")
    risk_score = state.get("risk_score", 0.0)
    escalation_reason = state.get("escalation_reason")

    if not escalation_reason:
        if risk_level == "HIGH":
            escalation_reason = f"Quarantined due to HIGH risk score ({risk_score:.2f}) and suspicious vector signals."
        else:
            escalation_reason = f"Automated recovery decision escalated to human oversight."

    if db and payment_id:
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if payment:
            payment.recovery_status = "IN_REVIEW"

        # Check or create HumanReview record
        review_record = db.query(HumanReview).filter(HumanReview.payment_id == payment_id).first()
        if not review_record:
            review_record = HumanReview(
                id=f"rev_{uuid.uuid4().hex[:10]}",
                payment_id=payment_id,
                status="PENDING",
                reason_for_quarantine=escalation_reason,
                quarantined_at=datetime.datetime.utcnow()
            )
            db.add(review_record)
        else:
            review_record.reason_for_quarantine = escalation_reason
            review_record.status = "PENDING"

        # Audit Event
        audit = AuditEvent(
            id=f"aud_{uuid.uuid4().hex[:10]}",
            payment_id=payment_id,
            event_type="ESCALATED_TO_HUMAN_REVIEW",
            actor="LangGraph Workflow Engine",
            details=f"Transaction safely quarantined for human review. Reason: {escalation_reason}",
            risk_level=risk_level,
            outcome="QUARANTINED",
            metadata_json={"risk_score": risk_score, "escalation_reason": escalation_reason}
        )
        db.add(audit)
        db.commit()

    trace = _append_trace(
        state,
        "HUMAN_REVIEW",
        "COMPLETED",
        f"Quarantined to Human Review Queue. Reason: {escalation_reason}"
    )

    return {
        "final_outcome": "ESCALATED",
        "escalation_reason": escalation_reason,
        "trace": trace,
        "current_step": "HUMAN_REVIEW"
    }

# ---------------------------------------------------------------------------
# Routing Functions (Conditional Edges)
# ---------------------------------------------------------------------------
def route_after_risk(state: RecoveryAgentState) -> str:
    """
    Branch after RISK_ASSESSMENT:
    - If HIGH risk or risk score >= 0.70 -> RISKY_UNCERTAIN (routes to HUMAN_REVIEW)
    - Otherwise -> BENIGN (routes to DIAGNOSE)
    """
    risk_level = state.get("risk_level", "LOW")
    risk_score = state.get("risk_score", 0.0)

    if risk_level == "HIGH" or (risk_score is not None and risk_score >= 0.70):
        logger.warning(f"Routing payment {state.get('payment_id')} to HUMAN_REVIEW due to HIGH risk ({risk_score})")
        return "RISKY_UNCERTAIN"
    
    return "BENIGN"

def route_after_decision(state: RecoveryAgentState) -> str:
    """
    Branch after RECOVERY_DECISION:
    - If ESCALATE -> ESCALATE (routes to HUMAN_REVIEW)
    - Otherwise -> EXECUTE (routes to EXECUTE_RECOVERY)
    """
    decision = state.get("recovery_decision") or {}
    if decision.get("action_type") == "ESCALATE" or not decision.get("is_permitted", True):
        return "ESCALATE"
    return "EXECUTE"

def route_after_verify(state: RecoveryAgentState) -> str:
    """
    Branch after VERIFY:
    - If SUCCESS -> SUCCESS (routes to END)
    - If RETRY and retry_count < max_retries -> RETRY (routes back to RECOVERY_DECISION)
    - If ESCALATE or retry limit exceeded -> ESCALATE (routes to HUMAN_REVIEW)
    """
    outcome = state.get("final_outcome", "SUCCESS")
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    if outcome == "SUCCESS":
        return "SUCCESS"
    elif outcome == "RETRY" and retry_count < max_retries:
        logger.info(f"Retrying recovery decision loop for {state.get('payment_id')} (Attempt {retry_count}/{max_retries})")
        return "RETRY"
    else:
        return "ESCALATE"
