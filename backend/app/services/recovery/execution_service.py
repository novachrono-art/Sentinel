import uuid
import datetime
import time
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.recovery_action import RecoveryAction
from app.models.audit_event import AuditEvent
from app.models.human_review import HumanReview
from app.models.risk_assessment import RiskAssessment
from app.services.recovery.recovery_decision_service import DecisionResult, RecoveryDecisionService
from app.providers.factory import get_payment_provider
from app.utils.logger import logger

@dataclass
class ExecutionResult:
    success: bool
    action_id: str
    action_type: str
    idempotency_key: str
    status: str  # "EXECUTED" | "BLOCKED" | "ESCALATED" | "FAILED"
    details: str
    attempt_number: int
    payload: Dict[str, Any] = field(default_factory=dict)
    gateway_response: Dict[str, Any] = field(default_factory=dict)
    executed_at: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())

class RecoveryExecutionService:
    """
    Guarded Recovery Execution Engine.
    Enforces the mandatory 6-step pre-flight safety checklist before firing any gateway action.
    Haults and escalates immediately if any ambiguity or safety breach is detected.
    """

    MAX_RETRY_LIMIT = 3
    MAX_AMOUNT_FOR_AUTO_RETRY = 50000.0

    @classmethod
    def execute_recovery_action(
        cls,
        db: Session,
        payment: Payment,
        decision: Optional[DecisionResult] = None,
        idempotency_key: Optional[str] = None,
    ) -> ExecutionResult:
        """
        Executes an approved recovery action through the payment gateway with strict guardrails:
          1. Check Risk Score
          2. Check Retry Count Bounds (Hard ceiling = 3)
          3. Check Payment State (Halt on ambiguous / already captured)
          4. Check Idempotency Key (Prevent double charges)
          5. Check Action Eligibility
          6. Execute & Record Result
        """
        if decision is None:
            decision = RecoveryDecisionService.decide_recovery_action(db, payment)

        current_retry = (payment.retry_count or 0) + 1
        action_id = f"act_{uuid.uuid4().hex[:10]}"
        if not idempotency_key:
            idempotency_key = f"idemp_{payment.id}_{decision.action_type}_{current_retry}_{uuid.uuid4().hex[:6]}"

        logger.info(
            f"Pre-flight safety checklist starting for payment {payment.id} "
            f"(Action: {decision.action_type}, Attempt: {current_retry}/{cls.MAX_RETRY_LIMIT})"
        )

        # -------------------------------------------------------------------
        # STEP 1: Check Risk Score & Level
        # -------------------------------------------------------------------
        risk = db.query(RiskAssessment).filter(RiskAssessment.payment_id == payment.id).first()
        risk_score = float(risk.risk_score) if risk and risk.risk_score else (decision.risk_score or 0.0)
        risk_level = risk.risk_level if risk and risk.risk_level else decision.risk_level

        if risk_level == "HIGH" or risk_score >= 0.70:
            logger.warning(f"Guardrail violation: High risk ({risk_score}) on {payment.id}. Escalating.")
            cls._escalate_to_human(db, payment, f"Safety Guardrail Block: High risk score ({risk_score:.2f})")
            return ExecutionResult(
                success=False,
                action_id=action_id,
                action_type=decision.action_type,
                idempotency_key=idempotency_key,
                status="BLOCKED",
                details="Blocked by Risk Guardrail: Transaction flagged as HIGH risk.",
                attempt_number=current_retry
            )

        # -------------------------------------------------------------------
        # STEP 2: Check Retry Count Bounds
        # -------------------------------------------------------------------
        if (payment.retry_count or 0) >= cls.MAX_RETRY_LIMIT:
            logger.warning(f"Guardrail violation: Max retries ({payment.retry_count}) reached on {payment.id}. Escalating.")
            cls._escalate_to_human(db, payment, f"Safety Guardrail Block: Max retries ({cls.MAX_RETRY_LIMIT}) exhausted.")
            return ExecutionResult(
                success=False,
                action_id=action_id,
                action_type=decision.action_type,
                idempotency_key=idempotency_key,
                status="BLOCKED",
                details=f"Blocked by Retry Cap: Max retry attempts ({cls.MAX_RETRY_LIMIT}) reached.",
                attempt_number=current_retry
            )

        # -------------------------------------------------------------------
        # STEP 3: Check Idempotency Lock
        # -------------------------------------------------------------------
        existing_action = db.query(RecoveryAction).filter(RecoveryAction.idempotency_key == idempotency_key).first()
        if existing_action:
            logger.error(f"Idempotency key collision for {idempotency_key}. Action suppressed.")
            return ExecutionResult(
                success=False,
                action_id=existing_action.id,
                action_type=existing_action.action_type,
                idempotency_key=idempotency_key,
                status="BLOCKED",
                details="Idempotency lock violation: Duplicate action payload detected.",
                attempt_number=current_retry
            )

        # -------------------------------------------------------------------
        # STEP 4: Check Payment State & Ambiguity
        # -------------------------------------------------------------------
        if payment.status in ["CAPTURED", "RECOVERED"]:
            logger.info(f"Payment {payment.id} is already captured/settled. Halting.")
            return ExecutionResult(
                success=True,
                action_id=action_id,
                action_type="NONE",
                idempotency_key=idempotency_key,
                status="BLOCKED",
                details="Payment is already settled/recovered. Duplicate recovery suppressed.",
                attempt_number=payment.retry_count
            )

        # Ambiguous State Detection
        if payment.status in ["PROCESSING", "PENDING_VERIFICATION", "AUTHORIZED_PENDING_CAPTURE"]:
            logger.warning(f"Ambiguous payment status '{payment.status}' for {payment.id}. Halting and escalating.")
            cls._escalate_to_human(db, payment, f"Ambiguous Payment State Detected: '{payment.status}'. Automated actions halted to prevent double charging.")
            return ExecutionResult(
                success=False,
                action_id=action_id,
                action_type=decision.action_type,
                idempotency_key=idempotency_key,
                status="ESCALATED",
                details=f"Automated action halted due to ambiguous payment status: '{payment.status}'.",
                attempt_number=current_retry
            )

        # -------------------------------------------------------------------
        # STEP 5: Check Action Eligibility & Decision Permission
        # -------------------------------------------------------------------
        if not decision.is_permitted or decision.action_type == "ESCALATE":
            cls._escalate_to_human(db, payment, decision.rationale)
            return ExecutionResult(
                success=False,
                action_id=action_id,
                action_type="ESCALATE",
                idempotency_key=idempotency_key,
                status="ESCALATED",
                details=f"Action not permitted by policy: {decision.rationale}",
                attempt_number=current_retry
            )

        # -------------------------------------------------------------------
        # STEP 6: Execute via Provider & Record Result
        # -------------------------------------------------------------------
        provider = get_payment_provider()
        gateway_res: Dict[str, Any] = {}
        payload: Dict[str, Any] = {}
        details: str = ""

        try:
            if decision.action_type == "RETRY":
                payload = {
                    "payment_id": payment.id,
                    "attempt_number": current_retry,
                    "amount": payment.amount,
                    "currency": payment.currency
                }
                gateway_res = provider.retry_payment(payment.id, idempotency_key)
                details = f"Executed direct gateway retry attempt #{current_retry} via Razorpay switch."

            elif decision.action_type == "CREATE_PAYMENT_LINK":
                cust_name = payment.customer.name if payment.customer else "Customer"
                cust_email = payment.customer.email if payment.customer else "customer@example.com"
                cust_phone = payment.customer.phone if payment.customer else None
                desc = f"Payment recovery link for order #{payment.id}"
                
                payload = {
                    "amount": payment.amount,
                    "currency": payment.currency,
                    "customer_name": cust_name,
                    "customer_email": cust_email,
                    "customer_phone": cust_phone,
                    "description": desc,
                    "idempotency_key": idempotency_key
                }
                gateway_res = provider.create_payment_link(
                    amount=payment.amount,
                    currency=payment.currency,
                    customer_name=cust_name,
                    customer_email=cust_email,
                    customer_phone=cust_phone,
                    description=desc,
                    idempotency_key=idempotency_key,
                    expire_by_hours=24
                )
                link_url = gateway_res.get("short_url") or f"https://rzp.io/i/{gateway_res.get('id', 'mock')}"
                details = f"Generated smart recovery payment link: {link_url}"

            elif decision.action_type == "SEND_REMINDER":
                payload = {"payment_id": payment.id, "channel": decision.channel}
                gateway_res = {"status": "queued", "channel": decision.channel}
                details = f"Dispatched payment reminder notification to customer via {decision.channel}."

            elif decision.action_type == "WAIT":
                payload = {"hold_seconds": 300}
                gateway_res = {"status": "holding"}
                details = "Holding for asynchronous webhook status resolution."

            # Update Payment & Record RecoveryAction
            payment.retry_count = current_retry
            if decision.action_type in ["RETRY", "CREATE_PAYMENT_LINK"] and gateway_res.get("status") in ["authorized", "captured", "created", "queued"]:
                payment.recovery_status = "RECOVERED"
                payment.status = "CAPTURED"
            else:
                payment.recovery_status = "RECOVERING"

            action_record = RecoveryAction(
                id=action_id,
                payment_id=payment.id,
                action_type=decision.action_type,
                idempotency_key=idempotency_key,
                status="EXECUTED",
                payload=payload,
                execution_result=gateway_res,
                executed_by="AI_AGENT",
                executed_at=datetime.datetime.utcnow()
            )
            db.add(action_record)

            # Record Audit Event
            audit = AuditEvent(
                id=f"aud_{uuid.uuid4().hex[:10]}",
                payment_id=payment.id,
                event_type="RECOVERY_ACTION_EXECUTED",
                actor="RecoveryExecutionEngine",
                details=f"Action [{decision.action_type}] Attempt #{current_retry}. {details}",
                risk_level=risk_level,
                outcome="EXECUTED",
                metadata_json={
                    "action_id": action_id,
                    "idempotency_key": idempotency_key,
                    "action_type": decision.action_type,
                    "attempt": current_retry
                }
            )
            db.add(audit)
            db.commit()

            logger.info(f"Recovery action {action_id} successfully executed for {payment.id}: {details}")

            return ExecutionResult(
                success=True,
                action_id=action_id,
                action_type=decision.action_type,
                idempotency_key=idempotency_key,
                status="EXECUTED",
                details=details,
                attempt_number=current_retry,
                payload=payload,
                gateway_response=gateway_res
            )

        except Exception as e:
            logger.error(f"Gateway execution failure for {payment.id}: {str(e)}")
            cls._escalate_to_human(db, payment, f"Gateway Execution Error: {str(e)}")
            return ExecutionResult(
                success=False,
                action_id=action_id,
                action_type=decision.action_type,
                idempotency_key=idempotency_key,
                status="FAILED",
                details=f"Gateway execution failed: {str(e)}",
                attempt_number=current_retry
            )

    @classmethod
    def _escalate_to_human(cls, db: Session, payment: Payment, reason: str):
        """Helper to safely quarantine transaction to human review."""
        payment.status = "IN_REVIEW"
        payment.recovery_status = "IN_REVIEW"
        hr = db.query(HumanReview).filter(HumanReview.payment_id == payment.id).first()
        if not hr:
            hr = HumanReview(
                id=f"rev_{uuid.uuid4().hex[:10]}",
                payment_id=payment.id,
                status="PENDING",
                reason_for_quarantine=reason,
                quarantined_at=datetime.datetime.utcnow()
            )
            db.add(hr)
        else:
            hr.reason_for_quarantine = reason
            hr.status = "PENDING"

        audit = AuditEvent(
            id=f"aud_{uuid.uuid4().hex[:10]}",
            payment_id=payment.id,
            event_type="ESCALATED_TO_HUMAN_REVIEW",
            actor="RecoveryExecutionEngine",
            details=f"Quarantined to human queue. Reason: {reason}",
            risk_level="HIGH" if "High risk" in reason else "MEDIUM",
            outcome="QUARANTINED",
            metadata_json={"escalation_reason": reason}
        )
        db.add(audit)
        db.commit()
