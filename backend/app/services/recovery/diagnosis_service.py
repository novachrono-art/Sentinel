import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from sqlalchemy.orm import Session
from app.models.payment import Payment
from app.utils.logger import logger

@dataclass
class DiagnosisResult:
    category: str  # "TEMPORARY_FAILURE" | "INSUFFICIENT_FUNDS" | "BANK_DECLINE" | "TIMEOUT" | "PAYMENT_METHOD_ISSUE" | "UNKNOWN"
    situation: str
    root_cause: str
    recommended_action: str  # "RETRY" | "CREATE_PAYMENT_LINK" | "SEND_REMINDER" | "WAIT" | "ESCALATE"
    confidence: float
    recovery_probability: float
    customer_message: str
    merchant_explanation: str
    diagnosed_at: str

class DiagnosisService:
    """
    AI-Powered Failure Diagnosis Service.
    Parses gateway error responses, payment attempts, and customer history
    to categorize failure conditions and synthesize actionable recovery intelligence.
    """

    # Comprehensive Gateway Error Taxonomy Mapping
    TAXONOMY_MAP = {
        "BANK_DECLINE_TEMPORARY": {
            "category": "TEMPORARY_FAILURE",
            "situation": "Temporary Issuing Bank Switch Congestion",
            "root_cause": "The customer's bank failed to respond in time due to temporary switch traffic or routine batch processing.",
            "recommended_action": "RETRY",
            "confidence": 0.96,
            "recovery_probability": 0.88,
            "customer_message": "Your bank experienced a momentary connection delay. We are automatically retrying your payment.",
            "merchant_explanation": "Transient bank processing timeout. Highly suitable for automated retry within 15 minutes."
        },
        "GATEWAY_TIMEOUT": {
            "category": "TIMEOUT",
            "situation": "Payment Gateway Timeout",
            "root_cause": "Upstream acquirer network timeout during authorization handshake.",
            "recommended_action": "RETRY",
            "confidence": 0.94,
            "recovery_probability": 0.82,
            "customer_message": "Network timeout during payment verification. Please wait a moment while we verify transaction status.",
            "merchant_explanation": "Acquirer switch timed out before completion. Eligible for status verification or instant retry."
        },
        "INSUFFICIENT_FUNDS": {
            "category": "INSUFFICIENT_FUNDS",
            "situation": "Insufficient Account Balance or Credit Limit",
            "root_cause": "Customer's account or card has insufficient balance/credit to complete this authorization.",
            "recommended_action": "CREATE_PAYMENT_LINK",
            "confidence": 0.98,
            "recovery_probability": 0.65,
            "customer_message": "Payment could not be completed due to insufficient funds. Click below to try another card, UPI, or netbanking.",
            "merchant_explanation": "Account balance depleted. Direct retry will fail; interactive payment link sent to allow secondary payment method."
        },
        "CARD_EXPIRED": {
            "category": "PAYMENT_METHOD_ISSUE",
            "situation": "Expired Payment Instrument",
            "root_cause": "The card expiration date provided precedes the current transaction date.",
            "recommended_action": "CREATE_PAYMENT_LINK",
            "confidence": 0.99,
            "recovery_probability": 0.70,
            "customer_message": "Your card has expired. Please use the secure link to update your card details or pay with UPI.",
            "merchant_explanation": "Card validity expired. Automated recharges blocked. Customer prompt required."
        },
        "AUTHENTICATION_FAILED": {
            "category": "PAYMENT_METHOD_ISSUE",
            "situation": "3D-Secure / OTP Verification Failure",
            "root_cause": "Customer entered an incorrect OTP or abandoned the 3D-Secure ACS verification page.",
            "recommended_action": "CREATE_PAYMENT_LINK",
            "confidence": 0.92,
            "recovery_probability": 0.74,
            "customer_message": "Verification was incomplete. Click here to resume your checkout with instant authentication.",
            "merchant_explanation": "3DS step-up authentication abandoned or invalid OTP. High conversion recovery via SMS/WhatsApp checkout link."
        },
        "BANK_DECLINE": {
            "category": "BANK_DECLINE",
            "situation": "Card Issuer Generic Decline",
            "root_cause": "Card issuing bank returned a generic decline (e.g. international transactions disabled or fraud filter triggered).",
            "recommended_action": "RETRY",
            "confidence": 0.89,
            "recovery_probability": 0.58,
            "customer_message": "Your bank declined the transaction. We are attempting a secondary retry or you can choose an alternate payment method.",
            "merchant_explanation": "Issuer decline code. One automated retry with backoff is permitted before link generation."
        },
        "CARD_VELOCITY_EXCEEDED": {
            "category": "UNKNOWN",
            "situation": "Velocity Limits Triggered",
            "root_cause": "Multiple rapid authorization attempts detected within an anomalous time window.",
            "recommended_action": "ESCALATE",
            "confidence": 0.95,
            "recovery_probability": 0.20,
            "customer_message": "Your transaction requires manual verification for your security.",
            "merchant_explanation": "Velocity anomalies detected. Automated recovery blocked to prevent dispute risk. Quarantined for review."
        }
    }

    @classmethod
    def diagnose(cls, payment: Payment) -> DiagnosisResult:
        """
        Synthesizes a DiagnosisResult from payment context, error code, description, and history.
        """
        error_code = (payment.error_code or "").upper().strip()
        error_desc = payment.error_description or ""

        # 1. Exact match in known taxonomy
        if error_code in cls.TAXONOMY_MAP:
            data = cls.TAXONOMY_MAP[error_code]
            # Contextual override: If it has already been retried once, escalate action to PAYMENT_LINK
            recommended_action = data["recommended_action"]
            if recommended_action == "RETRY" and payment.retry_count > 0:
                recommended_action = "CREATE_PAYMENT_LINK"

            return DiagnosisResult(
                category=data["category"],
                situation=data["situation"],
                root_cause=data["root_cause"],
                recommended_action=recommended_action,
                confidence=data["confidence"],
                recovery_probability=data["recovery_probability"],
                customer_message=data["customer_message"],
                merchant_explanation=data["merchant_explanation"],
                diagnosed_at=datetime.datetime.utcnow().isoformat()
            )

        # 2. Heuristic Pattern Matching
        if any(w in error_code or w in error_desc.upper() for w in ["TIMEOUT", "LATENCY", "GATEWAY_TIMEOUT"]):
            category = "TIMEOUT"
            situation = "Network or Switch Timeout"
            root_cause = f"Timeout encountered communicating with payment rail: {error_desc or error_code}."
            rec = "RETRY" if payment.retry_count == 0 else "CREATE_PAYMENT_LINK"
            conf = 0.85
            recov_prob = 0.78
            cust_msg = "A momentary network delay interrupted payment processing. Retrying now."
            merch_exp = "Network timeout detected. Safe for automated retry or reconciliation."

        elif any(w in error_code or w in error_desc.upper() for w in ["BALANCE", "INSUFFICIENT", "LIMIT_EXCEEDED"]):
            category = "INSUFFICIENT_FUNDS"
            situation = "Insufficient Balance / Limit"
            root_cause = f"Account lacks sufficient funds to cover authorization: {error_desc or error_code}."
            rec = "CREATE_PAYMENT_LINK"
            conf = 0.90
            recov_prob = 0.65
            cust_msg = "Insufficient funds detected. Please click the link to pay with another payment method."
            merch_exp = "Insufficient funds. Automated retry blocked; interactive recovery link advised."

        elif any(w in error_code or w in error_desc.upper() for w in ["EXPIRED", "INVALID", "CVV", "CREDENTIAL"]):
            category = "PAYMENT_METHOD_ISSUE"
            situation = "Invalid or Expired Payment Credential"
            root_cause = f"Payment credential verification failed: {error_desc or error_code}."
            rec = "CREATE_PAYMENT_LINK"
            conf = 0.88
            recov_prob = 0.72
            cust_msg = "Please update your payment method via the secure link to finish your purchase."
            merch_exp = "Payment method credential rejected. Customer action required."

        elif any(w in error_code or w in error_desc.upper() for w in ["TEMPORARY", "MAINTENANCE", "NETWORK", "502", "504"]):
            category = "TEMPORARY_FAILURE"
            situation = "Transient Processing Glitch"
            root_cause = f"Transient infrastructure failure: {error_desc or error_code}."
            rec = "RETRY" if payment.retry_count == 0 else "CREATE_PAYMENT_LINK"
            conf = 0.87
            recov_prob = 0.85
            cust_msg = "We encountered a temporary processing delay. Your order will be re-attempted shortly."
            merch_exp = "Transient infrastructure glitch. Immediate retry permitted."

        elif any(w in error_code or w in error_desc.upper() for w in ["DECLINE", "REJECT", "RESTRICTED", "HONOR"]):
            category = "BANK_DECLINE"
            situation = "Bank Authorization Decline"
            root_cause = f"Customer bank refused charge authorization: {error_desc or error_code}."
            rec = "RETRY" if payment.retry_count == 0 else "CREATE_PAYMENT_LINK"
            conf = 0.82
            recov_prob = 0.55
            cust_msg = "Your bank declined the charge. We are retrying or you can pay with an alternate method."
            merch_exp = "Issuer decline. Single retry allowed before issuing payment link."

        else:
            category = "UNKNOWN"
            situation = f"Unclassified Failure ({error_code or 'NO_CODE'})"
            root_cause = f"Unrecognized failure condition from payment gateway: {error_desc or 'No description provided'}."
            rec = "CREATE_PAYMENT_LINK" if payment.retry_count < 2 else "ESCALATE"
            conf = 0.60
            recov_prob = 0.40
            cust_msg = "We were unable to complete your payment. Please use the secure link to retry."
            merch_exp = "Unclassified gateway error. Interactive payment link recommended."

        return DiagnosisResult(
            category=category,
            situation=situation,
            root_cause=root_cause,
            recommended_action=rec,
            confidence=conf,
            recovery_probability=recov_prob,
            customer_message=cust_msg,
            merchant_explanation=merch_exp,
            diagnosed_at=datetime.datetime.utcnow().isoformat()
        )

    @classmethod
    def diagnose_and_persist(cls, db: Session, payment_id: str) -> DiagnosisResult:
        """
        Diagnoses payment and updates Payment record ai_diagnosis in SQLite.
        """
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            raise ValueError(f"Payment '{payment_id}' not found.")

        result = cls.diagnose(payment)

        # Update database fields
        payment.ai_diagnosis = f"[{result.category}] {result.situation}: {result.root_cause}"
        payment.recommended_action = result.recommended_action
        db.commit()

        logger.info(f"Diagnosed payment {payment.id}: Category=[{result.category}], Action=[{result.recommended_action}]")
        return result
