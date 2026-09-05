import numpy as np
from types import SimpleNamespace
from typing import Dict, Any, Tuple, List
from app.models.payment import Payment
from app.models.customer import Customer

DISPOSABLE_EMAIL_DOMAINS = {
    "disposable-mail.io", "tempmail.com", "burnermail.io", "mailinator.com",
    "10minutemail.com", "guerrillamail.com", "sharklasers.com", "yopmail.com",
    "unknown-domain.io", "throwawaymail.com"
}

ERROR_SEVERITY_MAP = {
    "BANK_DECLINE_TEMPORARY": 0.10,
    "UPI_GATEWAY_TIMEOUT": 0.20,
    "GATEWAY_ERROR": 0.25,
    "CARD_EXPIRED": 0.35,
    "INSUFFICIENT_FUNDS": 0.40,
    "MANDATE_EXHAUSTED": 0.65,
    "CARD_DECLINED_FRAUD": 0.90,
    "CARD_VELOCITY_EXCEEDED": 0.95,
    "SUSPICIOUS_TRANSACTION": 0.95
}

class FeatureExtractor:
    @staticmethod
    def extract_features(payment: Payment, customer: Customer) -> Tuple[np.ndarray, Dict[str, float], List[str]]:
        """
        Extract and scale the 8 deterministic risk features.
        Returns:
          - feature_vector (numpy array of shape (1, 8))
          - feature_dict (human-readable scaled feature names and values)
          - detected_signals (list of textual risk indicators)
        """
        # Gracefully handle missing customer records by using neutral defaults
        if customer is None:
            customer = SimpleNamespace(
                lifetime_successful_orders=0,
                dispute_count=0,
                email="",
                total_spend=0.0,
            )

        signals: List[str] = []

        # 0. Amount scaled (Rs.100 to Rs.200,000)
        amount = float(payment.amount or 1000.0)
        amount_scaled = float(np.clip((amount - 100.0) / (200000.0 - 100.0), 0.0, 1.0))
        if amount >= 25000.0:
            signals.append(f"High-Value Transaction: Rs.{amount:,.2f}")

        # 1. Customer Order History
        orders = int(customer.lifetime_successful_orders or 0)
        orders_scaled = float(np.clip(orders / 15.0, 0.0, 1.0))
        if orders >= 3:
            signals.append(f"Established Customer: {orders} Successful Past Orders")
        elif orders == 0:
            signals.append("New Customer / Zero Previous Order History")

        # 2. Dispute / Chargeback Count
        disputes = int(customer.dispute_count or 0)
        dispute_scaled = float(np.clip(disputes / 3.0, 0.0, 1.0))
        if disputes > 0:
            signals.append(f"Past Disputes Flagged: {disputes} Chargeback Events")

        # 3. Velocity Score
        is_velocity_err = (payment.error_code == "CARD_VELOCITY_EXCEEDED")
        velocity_score = 0.90 if is_velocity_err else 0.15
        if is_velocity_err:
            signals.append("High Card Velocity: Multiple attempts in short time window")

        # 4. Disposable Email Flag
        email = (customer.email or "").lower().strip()
        domain = email.split("@")[-1] if "@" in email else ""
        is_disposable = 1.0 if domain in DISPOSABLE_EMAIL_DOMAINS else 0.0
        if is_disposable:
            signals.append(f"Suspicious Email Domain: @{domain}")

        # 5. Error Code Severity
        error_code = (payment.error_code or "GATEWAY_ERROR").upper()
        error_severity = ERROR_SEVERITY_MAP.get(error_code, 0.30)
        if error_severity <= 0.20:
            signals.append(f"Transient Gateway/Bank Failure ({error_code})")
        elif error_severity >= 0.80:
            signals.append(f"Critical Gateway Risk Code ({error_code})")

        # 6. Retry Exhaustion Ratio
        retries = int(payment.retry_count or 0)
        max_retries = int(payment.max_retries or 3)
        retry_ratio = float(np.clip(retries / max(max_retries, 1), 0.0, 1.0))
        if retries >= max_retries:
            signals.append(f"Maximum Retry Limit Reached ({retries}/{max_retries})")

        # 7. Customer Lifetime Spend Scaled (Rs.0 to Rs.50,000)
        spend = float(customer.total_spend or (orders * 2500.0))
        spend_scaled = float(np.clip(spend / 50000.0, 0.0, 1.0))
        if spend >= 10000.0:
            signals.append(f"High-LTV Customer: Rs.{spend:,.2f} Total Spend")

        # Combine into numpy array
        vector = np.array([[
            amount_scaled,
            orders_scaled,
            dispute_scaled,
            velocity_score,
            is_disposable,
            error_severity,
            retry_ratio,
            spend_scaled
        ]], dtype=np.float32)

        feature_dict = {
            "amount_scaled": round(amount_scaled, 4),
            "order_history_scaled": round(orders_scaled, 4),
            "dispute_count_scaled": round(dispute_scaled, 4),
            "velocity_score": round(velocity_score, 4),
            "disposable_email": round(is_disposable, 4),
            "error_severity": round(error_severity, 4),
            "retry_ratio": round(retry_ratio, 4),
            "lifetime_spend_scaled": round(spend_scaled, 4)
        }

        return vector, feature_dict, signals
