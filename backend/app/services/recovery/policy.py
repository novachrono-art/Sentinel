from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

@dataclass
class PolicyEvaluationResult:
    is_permitted: bool
    final_action: str
    channel: str
    reason: str
    rules_applied: List[str] = field(default_factory=list)

class RecoveryPolicyEngine:
    """
    Deterministic FinTech Guardrail Engine.
    Ensures that LLM or heuristic recommendations NEVER violate merchant safety,
    risk ceilings, or regulatory retry limits.
    """

    MAX_RETRIES_DEFAULT = 3
    MAX_AUTO_RETRY_AMOUNT_INR = 50000.0  # Automated charge retries capped at ₹50,000

    @classmethod
    def evaluate(
        cls,
        recommended_action: str,
        failure_category: str,
        risk_score: float,
        risk_level: str,
        retry_count: int,
        max_retries: int,
        amount: float,
        payment_status: str
    ) -> PolicyEvaluationResult:
        rules_applied: List[str] = []

        # Rule 1: Idempotency / Already Settled Check
        if payment_status in ["CAPTURED", "RECOVERED"]:
            rules_applied.append("RULE_ALREADY_SETTLED")
            return PolicyEvaluationResult(
                is_permitted=False,
                final_action="WAIT",
                channel="NONE",
                reason="Payment is already settled or captured. No recovery action permitted.",
                rules_applied=rules_applied
            )

        # Rule 2: Risk Ceiling Guardrail
        if risk_level == "HIGH" or risk_score >= 0.70:
            rules_applied.append("RULE_HIGH_RISK_BLOCK")
            return PolicyEvaluationResult(
                is_permitted=False,
                final_action="ESCALATE",
                channel="INTERNAL_REVIEW_QUEUE",
                reason=f"High risk score ({risk_score:.2f}, level {risk_level}) violates automated recovery ceiling.",
                rules_applied=rules_applied
            )

        # Rule 3: Hard Maximum Retries Guardrail
        if retry_count >= max_retries:
            rules_applied.append("RULE_MAX_RETRIES_EXCEEDED")
            return PolicyEvaluationResult(
                is_permitted=False,
                final_action="ESCALATE",
                channel="INTERNAL_REVIEW_QUEUE",
                reason=f"Maximum allowed automated recovery attempts ({retry_count}/{max_retries}) exhausted.",
                rules_applied=rules_applied
            )

        # Rule 4: Action Amount Threshold
        if recommended_action == "RETRY" and amount > cls.MAX_AUTO_RETRY_AMOUNT_INR:
            rules_applied.append("RULE_AMOUNT_EXCEEDS_DIRECT_RETRY_THRESHOLD")
            return PolicyEvaluationResult(
                is_permitted=True,
                final_action="CREATE_PAYMENT_LINK",
                channel="EMAIL_AND_SMS",
                reason=f"Transaction amount (₹{amount:,.2f}) exceeds auto-retry ceiling (₹{cls.MAX_AUTO_RETRY_AMOUNT_INR:,.2f}). Downgraded to interactive payment link.",
                rules_applied=rules_applied
            )

        # Rule 5: Category Action Compatibility
        if recommended_action == "RETRY":
            if failure_category in ["INSUFFICIENT_FUNDS", "PAYMENT_METHOD_ISSUE"]:
                rules_applied.append("RULE_INCOMPATIBLE_DIRECT_RETRY")
                return PolicyEvaluationResult(
                    is_permitted=True,
                    final_action="CREATE_PAYMENT_LINK",
                    channel="EMAIL_AND_SMS",
                    reason=f"Direct retry disallowed for category [{failure_category}]. Switched to payment link for alternative payment method selection.",
                    rules_applied=rules_applied
                )
            if retry_count > 0 and failure_category == "BANK_DECLINE":
                rules_applied.append("RULE_SECONDARY_DECLINE_LINK_FALLBACK")
                return PolicyEvaluationResult(
                    is_permitted=True,
                    final_action="CREATE_PAYMENT_LINK",
                    channel="EMAIL_AND_SMS",
                    reason="Subsequent bank decline retry prohibited. Switched to smart recovery link.",
                    rules_applied=rules_applied
                )
            
            rules_applied.append("RULE_DIRECT_RETRY_PERMITTED")
            return PolicyEvaluationResult(
                is_permitted=True,
                final_action="RETRY",
                channel="DIRECT_GATEWAY",
                reason="Transient gateway failure within safe risk & retry limits. Immediate retry permitted.",
                rules_applied=rules_applied
            )

        # Rule 6: Payment Link Strategy
        if recommended_action == "CREATE_PAYMENT_LINK":
            rules_applied.append("RULE_PAYMENT_LINK_PERMITTED")
            return PolicyEvaluationResult(
                is_permitted=True,
                final_action="CREATE_PAYMENT_LINK",
                channel="EMAIL_AND_SMS",
                reason=f"Interactive checkout link approved for category [{failure_category}].",
                rules_applied=rules_applied
            )

        # Rule 7: Reminder Strategy
        if recommended_action == "SEND_REMINDER":
            rules_applied.append("RULE_REMINDER_PERMITTED")
            return PolicyEvaluationResult(
                is_permitted=True,
                final_action="SEND_REMINDER",
                channel="WHATSAPP_AND_SMS",
                reason="Payment reminder approved for outstanding unrecovered transaction.",
                rules_applied=rules_applied
            )

        # Rule 8: Wait / Asynchronous Pending
        if recommended_action == "WAIT":
            rules_applied.append("RULE_WAIT_PERMITTED")
            return PolicyEvaluationResult(
                is_permitted=True,
                final_action="WAIT",
                channel="NONE",
                reason="Asynchronous webhook reconciliation in progress. Hold for status callback.",
                rules_applied=rules_applied
            )

        # Default Fallback: Safe Escalation
        rules_applied.append("RULE_DEFAULT_FALLBACK_ESCALATION")
        return PolicyEvaluationResult(
            is_permitted=False,
            final_action="ESCALATE",
            channel="INTERNAL_REVIEW_QUEUE",
            reason=f"Unrecognized or unapproved action recommendation: {recommended_action}",
            rules_applied=rules_applied
        )
