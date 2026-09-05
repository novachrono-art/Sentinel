import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.risk_assessment import RiskAssessment
from app.services.recovery.diagnosis_service import DiagnosisService, DiagnosisResult
from app.services.recovery.policy import RecoveryPolicyEngine, PolicyEvaluationResult
from app.services.risk.risk_service import RiskAssessmentService
from app.utils.logger import logger

@dataclass
class DecisionResult:
    action_type: str  # "RETRY" | "CREATE_PAYMENT_LINK" | "SEND_REMINDER" | "WAIT" | "ESCALATE"
    channel: str      # "DIRECT_GATEWAY" | "EMAIL_AND_SMS" | "WHATSAPP_AND_SMS" | "INTERNAL_REVIEW_QUEUE" | "NONE"
    is_permitted: bool
    rationale: str
    failure_category: str
    risk_score: float
    risk_level: str
    retry_count: int
    max_retries: int
    policy_rules_applied: List[str]
    parameters: Dict[str, Any]
    decided_at: str

class RecoveryDecisionService:
    """
    Stateful Recovery Decision & Strategy Service.
    Arbitrates failure diagnosis, deterministic policy guardrails, and risk thresholds
    to arrive at the optimal, compliant recovery action.
    """

    @classmethod
    def decide_recovery_action(
        cls,
        db: Session,
        payment: Payment,
        diagnosis: Optional[DiagnosisResult] = None,
        risk_assessment: Optional[RiskAssessment] = None
    ) -> DecisionResult:
        # 1. Obtain Diagnosis if not provided
        if diagnosis is None:
            diagnosis = DiagnosisService.diagnose(payment)

        # 2. Obtain Risk Assessment if not provided
        if risk_assessment is None:
            risk_assessment = db.query(RiskAssessment).filter(RiskAssessment.payment_id == payment.id).first()
            if not risk_assessment:
                risk_assessment = RiskAssessmentService.evaluate_payment_risk(db, payment)

        risk_score = float(risk_assessment.risk_score or 0.50)
        risk_level = risk_assessment.risk_level or "MEDIUM"
        retry_count = payment.retry_count or 0
        max_retries = payment.max_retries or 3

        # 3. Evaluate action through Deterministic Policy Engine
        policy_res: PolicyEvaluationResult = RecoveryPolicyEngine.evaluate(
            recommended_action=diagnosis.recommended_action,
            failure_category=diagnosis.category,
            risk_score=risk_score,
            risk_level=risk_level,
            retry_count=retry_count,
            max_retries=max_retries,
            amount=payment.amount,
            payment_status=payment.status
        )

        # 4. Generate parameters specific to the decided action
        parameters: Dict[str, Any] = {
            "attempt_number": retry_count + 1,
            "max_allowed_attempts": max_retries
        }

        if policy_res.final_action == "RETRY":
            parameters["backoff_seconds"] = 300 if retry_count == 0 else 900
            parameters["gateway_provider"] = "Razorpay"
        elif policy_res.final_action == "CREATE_PAYMENT_LINK":
            parameters["link_expiry_hours"] = 24
            parameters["customer_email"] = payment.customer.email if payment.customer else None
            parameters["customer_phone"] = payment.customer.phone if payment.customer else None
            parameters["supported_methods"] = ["card", "upi", "netbanking", "wallet"]
        elif policy_res.final_action == "SEND_REMINDER":
            parameters["channels"] = ["SMS", "WhatsApp"]
            parameters["reminder_template"] = "payment_recovery_prompt_v1"
        elif policy_res.final_action == "WAIT":
            parameters["reconciliation_timeout_seconds"] = 600
        elif policy_res.final_action == "ESCALATE":
            parameters["escalation_queue"] = "FINTECH_HUMAN_REVIEW"
            parameters["escalation_priority"] = "HIGH" if risk_level == "HIGH" else "NORMAL"

        decision = DecisionResult(
            action_type=policy_res.final_action,
            channel=policy_res.channel,
            is_permitted=policy_res.is_permitted,
            rationale=policy_res.reason,
            failure_category=diagnosis.category,
            risk_score=risk_score,
            risk_level=risk_level,
            retry_count=retry_count,
            max_retries=max_retries,
            policy_rules_applied=policy_res.rules_applied,
            parameters=parameters,
            decided_at=datetime.datetime.utcnow().isoformat()
        )

        logger.info(
            f"Recovery decision for {payment.id}: Action={decision.action_type}, "
            f"Permitted={decision.is_permitted}, Channel={decision.channel}, Reason={decision.rationale}"
        )
        return decision

    @classmethod
    def decide_and_persist(cls, db: Session, payment_id: str) -> DecisionResult:
        """
        Executes decision service for payment and updates recommended_action on payment record.
        """
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            raise ValueError(f"Payment with ID '{payment_id}' not found.")

        decision = cls.decide_recovery_action(db, payment)
        payment.recommended_action = decision.action_type
        db.commit()

        return decision
