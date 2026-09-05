import datetime
from typing import TypedDict, Optional, Dict, Any, List

class RecoveryAgentState(TypedDict, total=False):
    """
    Core state for the LangGraph Payment Recovery Agent Workflow.
    Represents the full transactional lifecycle across all nodes.
    """
    # Identifiers
    run_id: str
    payment_id: str
    merchant_id: Optional[str]
    customer_id: Optional[str]

    # Payment Snapshot
    payment: Optional[Dict[str, Any]]

    # Risk Assessment Outcome
    risk_assessment: Optional[Dict[str, Any]]
    risk_score: Optional[float]
    risk_level: Optional[str]  # "LOW" | "MEDIUM" | "HIGH"
    risk_signals: List[str]

    # Failure Diagnosis
    diagnosis: Optional[Dict[str, Any]]  # { category, situation, explanation, recommended_action }

    # Recovery Decision & Strategy
    recovery_decision: Optional[Dict[str, Any]]  # { action_type, channel, reason, is_permitted }

    # Recovery Execution Attempt
    recovery_attempt: Optional[Dict[str, Any]]  # { action_id, idempotency_key, status, details }

    # Outcome Verification
    verification: Optional[Dict[str, Any]]  # { verified, payment_status, recovered_amount, message }

    # Guardrail Controls & Limits
    retry_count: int
    max_retries: int

    # Final Outcome & Escalation Reason
    final_outcome: Optional[str]  # "SUCCESS" | "RETRY" | "ESCALATED" | "FAILED"
    escalation_reason: Optional[str]

    # Execution Step Trace for Full Auditability
    trace: List[Dict[str, Any]]
    current_step: str
    error: Optional[str]
