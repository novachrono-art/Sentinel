from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any, List

from app.database.session import get_db
from app.models.payment import Payment
from app.services.recovery.diagnosis_service import DiagnosisService
from app.services.recovery.recovery_decision_service import RecoveryDecisionService
from app.services.recovery.policy import RecoveryPolicyEngine
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

router = APIRouter(prefix="/recovery", tags=["Failure Diagnosis & Recovery Strategy"])

@router.post("/diagnose/{payment_id}")
def diagnose_payment(
    payment_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Executes AI failure diagnosis on a payment.
    Categorizes the error into the standardized failure taxonomy and formulates explainability narratives.
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment with ID '{payment_id}' not found."
        )

    try:
        diagnosis = DiagnosisService.diagnose_and_persist(db, payment_id)
        return {
            "status": "success",
            "payment_id": payment_id,
            "diagnosis": {
                "category": diagnosis.category,
                "situation": diagnosis.situation,
                "root_cause": diagnosis.root_cause,
                "recommended_action": diagnosis.recommended_action,
                "confidence": diagnosis.confidence,
                "recovery_probability": diagnosis.recovery_probability,
                "customer_message": diagnosis.customer_message,
                "merchant_explanation": diagnosis.merchant_explanation,
                "diagnosed_at": diagnosis.diagnosed_at
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Diagnosis failed: {str(e)}"
        )

@router.post("/decision/{payment_id}")
def decide_recovery_strategy(
    payment_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Evaluates failure diagnosis, risk scores, and deterministic backend policy guardrails
    to determine the optimal recovery strategy and execution channel.
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment with ID '{payment_id}' not found."
        )

    try:
        decision = RecoveryDecisionService.decide_and_persist(db, payment_id)
        return {
            "status": "success",
            "payment_id": payment_id,
            "decision": {
                "action_type": decision.action_type,
                "channel": decision.channel,
                "is_permitted": decision.is_permitted,
                "rationale": decision.rationale,
                "failure_category": decision.failure_category,
                "risk_score": decision.risk_score,
                "risk_level": decision.risk_level,
                "retry_count": decision.retry_count,
                "max_retries": decision.max_retries,
                "policy_rules_applied": decision.policy_rules_applied,
                "parameters": decision.parameters,
                "decided_at": decision.decided_at
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Recovery strategy calculation failed: {str(e)}"
        )

@router.get("/taxonomy")
def get_failure_taxonomy(current_user: UserProfile = Depends(get_current_user)):
    """
    Returns the failure situations, categories, and mapping matrix.
    """
    return {
        "categories": [
            {
                "code": "TEMPORARY_FAILURE",
                "label": "Temporary Network / Bank Switch Glitch",
                "primary_action": "RETRY",
                "expected_recovery_rate": "80% - 90%"
            },
            {
                "code": "INSUFFICIENT_FUNDS",
                "label": "Customer Balance / Limit Depleted",
                "primary_action": "CREATE_PAYMENT_LINK",
                "expected_recovery_rate": "60% - 70%"
            },
            {
                "code": "BANK_DECLINE",
                "label": "Card Issuing Bank Decline",
                "primary_action": "RETRY_THEN_LINK",
                "expected_recovery_rate": "50% - 60%"
            },
            {
                "code": "TIMEOUT",
                "label": "Gateway / Switch Latency Timeout",
                "primary_action": "RETRY",
                "expected_recovery_rate": "75% - 85%"
            },
            {
                "code": "PAYMENT_METHOD_ISSUE",
                "label": "Card Expired or 3DS Auth Failed",
                "primary_action": "CREATE_PAYMENT_LINK",
                "expected_recovery_rate": "65% - 75%"
            },
            {
                "code": "UNKNOWN",
                "label": "Unclassified Gateway Response",
                "primary_action": "CREATE_PAYMENT_LINK_OR_ESCALATE",
                "expected_recovery_rate": "30% - 50%"
            }
        ],
        "recovery_actions": [
            "RETRY",
            "CREATE_PAYMENT_LINK",
            "SEND_REMINDER",
            "WAIT",
            "ESCALATE"
        ]
    }

@router.get("/policy-rules")
def get_policy_rules(current_user: UserProfile = Depends(get_current_user)):
    """
    Returns the active deterministic financial safety guardrails and policy ceilings.
    """
    return {
        "max_retries_ceiling": RecoveryPolicyEngine.MAX_RETRIES_DEFAULT,
        "max_auto_retry_amount_inr": RecoveryPolicyEngine.MAX_AUTO_RETRY_AMOUNT_INR,
        "high_risk_quarantine_floor": 0.70,
        "rules": [
            {
                "rule_id": "RULE_HIGH_RISK_BLOCK",
                "description": "Transactions with risk score >= 0.70 or HIGH level are strictly blocked from automated retries and quarantined."
            },
            {
                "rule_id": "RULE_MAX_RETRIES_EXCEEDED",
                "description": "Any transaction with attempts >= max_retries is immediately escalated to human review."
            },
            {
                "rule_id": "RULE_AMOUNT_EXCEEDS_DIRECT_RETRY_THRESHOLD",
                "description": "Amounts above ₹50,000 cannot be silently re-charged; downgraded to interactive payment link."
            },
            {
                "rule_id": "RULE_INCOMPATIBLE_DIRECT_RETRY",
                "description": "Categories like INSUFFICIENT_FUNDS or PAYMENT_METHOD_ISSUE require link generation instead of direct retries."
            },
            {
                "rule_id": "RULE_ALREADY_SETTLED",
                "description": "Captured or recovered transactions are idempotently locked from further recovery operations."
            }
        ]
    }
