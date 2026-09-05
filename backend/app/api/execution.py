from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional

from pydantic import BaseModel
from app.database.session import get_db
from app.models.payment import Payment
from app.models.recovery_action import RecoveryAction
from app.models.risk_assessment import RiskAssessment
from app.services.recovery.execution_service import RecoveryExecutionService
from app.services.recovery.recovery_decision_service import RecoveryDecisionService
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

router = APIRouter(prefix="/execution", tags=["Recovery Execution & Guardrails"])

class ExecuteRequest(BaseModel):
    idempotency_key: Optional[str] = None

@router.post("/execute/{payment_id}")
def execute_payment_recovery(
    payment_id: str,
    body: Optional[ExecuteRequest] = None,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Executes a recovery action on a failed payment with the full 6-step safety checklist:
    1. Check risk score (< 0.70)
    2. Check retry count bounds (ceiling = 3)
    3. Check payment state (halts if captured or ambiguous)
    4. Check idempotency lock (prevents duplicate execution)
    5. Check action eligibility
    6. Execute & record result in recovery_actions and audit_events.
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment with ID '{payment_id}' was not found."
        )

    # Merchant tenant check
    if current_user.role == "merchant" and current_user.merchant_id:
        if payment.merchant_id not in [current_user.merchant_id, "mer_rzp_default", "mer_test_01"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to execute recovery actions on this merchant's payments."
            )

    try:
        idemp = body.idempotency_key if body else None
        exec_res = RecoveryExecutionService.execute_recovery_action(db, payment, idempotency_key=idemp)
        return {
            "status": "success" if exec_res.success else "blocked",
            "payment_id": payment.id,
            "action_id": exec_res.action_id,
            "action_type": exec_res.action_type,
            "execution_status": exec_res.status,
            "idempotency_key": exec_res.idempotency_key,
            "attempt_number": exec_res.attempt_number,
            "details": exec_res.details,
            "gateway_response": exec_res.gateway_response,
            "executed_at": exec_res.executed_at
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Recovery execution failed: {str(e)}"
        )

@router.get("/history/{payment_id}")
def get_payment_recovery_actions(
    payment_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Fetches all historical RecoveryAction entries executed for a payment,
    including idempotency keys and gateway response snapshots.
    """
    actions = (
        db.query(RecoveryAction)
        .filter(RecoveryAction.payment_id == payment_id)
        .order_by(RecoveryAction.executed_at.desc())
        .all()
    )

    return [
        {
            "id": act.id,
            "payment_id": act.payment_id,
            "action_type": act.action_type,
            "idempotency_key": act.idempotency_key,
            "status": act.status,
            "payload": act.payload,
            "execution_result": act.execution_result,
            "executed_by": act.executed_by,
            "executed_at": act.executed_at.isoformat() if act.executed_at else None
        }
        for act in actions
    ]

@router.get("/guardrail-status/{payment_id}")
def check_guardrails(
    payment_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Evaluates all 6 safety checks for a payment without firing any external gateway requests.
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment with ID '{payment_id}' was not found."
        )

    risk = db.query(RiskAssessment).filter(RiskAssessment.payment_id == payment_id).first()
    risk_score = float(risk.risk_score) if risk and risk.risk_score else 0.0
    risk_level = risk.risk_level if risk and risk.risk_level else "UNKNOWN"
    retry_count = payment.retry_count or 0
    max_retries = payment.max_retries or 3

    decision = RecoveryDecisionService.decide_recovery_action(db, payment)

    # Evaluate individual guardrails
    risk_passed = (risk_level != "HIGH" and risk_score < 0.70)
    retry_passed = (retry_count < max_retries)
    state_passed = (payment.status not in ["CAPTURED", "RECOVERED", "PROCESSING", "PENDING_VERIFICATION"])
    action_eligible = decision.is_permitted and decision.action_type != "ESCALATE"

    all_passed = risk_passed and retry_passed and state_passed and action_eligible

    return {
        "payment_id": payment_id,
        "eligible_for_execution": all_passed,
        "proposed_action": decision.action_type,
        "proposed_channel": decision.channel,
        "guardrail_checks": {
            "risk_score_gate": {
                "passed": risk_passed,
                "current_score": risk_score,
                "threshold": 0.70,
                "risk_level": risk_level
            },
            "retry_ceiling_gate": {
                "passed": retry_passed,
                "attempts_used": retry_count,
                "max_attempts": max_retries
            },
            "payment_state_gate": {
                "passed": state_passed,
                "current_status": payment.status,
                "ambiguous": payment.status in ["PROCESSING", "PENDING_VERIFICATION"]
            },
            "action_policy_gate": {
                "passed": action_eligible,
                "policy_reason": decision.rationale
            }
        }
    }
