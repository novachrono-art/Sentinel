import uuid
import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.payment_attempt import PaymentAttempt
from app.models.audit_event import AuditEvent
from app.models.risk_assessment import RiskAssessment
from app.utils.logger import logger

class IngestionService:
    @staticmethod
    def ensure_default_merchant(db: Session) -> Merchant:
        merchant = db.query(Merchant).filter(Merchant.id == "mer_rzp_default").first()
        if not merchant:
            merchant = Merchant(
                id="mer_rzp_default",
                business_name="Apex Commerce Pvt Ltd",
                contact_email="ops@apexcommerce.io",
                is_live=False
            )
            db.add(merchant)
            db.commit()
            db.refresh(merchant)
        return merchant

    @staticmethod
    def get_or_create_customer(
        db: Session,
        merchant_id: str,
        name: str,
        email: str,
        phone: Optional[str] = None,
        history_orders: int = 0
    ) -> Customer:
        customer = db.query(Customer).filter(Customer.email == email, Customer.merchant_id == merchant_id).first()
        if not customer:
            customer = Customer(
                id=f"cust_{uuid.uuid4().hex[:10]}",
                merchant_id=merchant_id,
                name=name,
                email=email,
                phone=phone or "+919876543210",
                lifetime_successful_orders=history_orders,
                lifetime_failed_orders=1,
                total_spend=float(history_orders * 2500.0),
                dispute_count=0
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)
        return customer

    @staticmethod
    def ingest_webhook_event(db: Session, event_data: Dict[str, Any]) -> Payment:
        """
        Normalize and ingest a real or test Razorpay webhook payload.
        """
        event_type = event_data.get("event", "payment.failed")
        payload = event_data.get("payload", {})
        payment_entity = payload.get("payment", {}).get("entity", {})
        
        payment_id = payment_entity.get("id", f"pay_rzp_{uuid.uuid4().hex[:10]}")
        amount_in_paise = payment_entity.get("amount", 0)
        amount = float(amount_in_paise / 100.0) if amount_in_paise > 0 else 1000.0
        currency = payment_entity.get("currency", "INR")
        
        customer_email = payment_entity.get("email") or "customer@example.com"
        customer_contact = payment_entity.get("contact") or "+919876543210"
        customer_name = customer_email.split("@")[0].replace(".", " ").title()

        error_code = payment_entity.get("error_code") or "GATEWAY_ERROR"
        error_desc = payment_entity.get("error_description") or "Payment authorization failed"
        failure_reason = f"{error_code}: {error_desc}"

        merchant = IngestionService.ensure_default_merchant(db)
        customer = IngestionService.get_or_create_customer(
            db=db,
            merchant_id=merchant.id,
            name=customer_name,
            email=customer_email,
            phone=customer_contact,
            history_orders=2
        )

        existing = db.query(Payment).filter(Payment.id == payment_id).first()
        if existing:
            existing.status = "FAILED" if "failed" in event_type else "RECOVERED"
            existing.error_code = error_code
            existing.failure_reason = failure_reason
            db.commit()
            return existing

        payment = Payment(
            id=payment_id,
            merchant_id=merchant.id,
            customer_id=customer.id,
            amount=amount,
            currency=currency,
            status="FAILED",
            error_code=error_code,
            error_description=error_desc,
            failure_reason=failure_reason,
            recovery_status="FAILED",
            retry_count=0,
            max_retries=3
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)

        # Record Initial Attempt
        attempt = PaymentAttempt(
            id=f"att_{uuid.uuid4().hex[:10]}",
            payment_id=payment.id,
            attempt_number=1,
            status="FAILED",
            gateway_response_code=error_code,
            gateway_response_body=error_desc,
            latency_ms=185.0
        )
        db.add(attempt)

        # Record Audit Event
        audit = AuditEvent(
            id=f"aud_{uuid.uuid4().hex[:10]}",
            payment_id=payment.id,
            event_type="FAILURE_INGESTED",
            actor="Razorpay Provider Adapter",
            details=f"Ingested payment failure for ₹{amount:,.2f} ({customer_email}). Reason: {failure_reason}",
            risk_level="PENDING",
            outcome="INGESTED"
        )
        db.add(audit)
        db.commit()

        logger.info(f"Successfully ingested payment failure {payment.id} for ₹{amount}")
        return payment

    @staticmethod
    def simulate_failure_scenario(db: Session, scenario_key: str) -> Payment:
        """
        Inject a specific deterministic failure scenario for testing and demonstration.
        """
        scenarios = {
            "BANK_DECLINE_TEMPORARY": {
                "name": "Rahul Sharma",
                "email": "rahul.sharma@example.com",
                "amount": 4999.0,
                "history_orders": 4,
                "error_code": "BANK_DECLINE_TEMPORARY",
                "reason": "Temporary bank decline (Insufficient balance response from issuing bank)",
                "ai_diagnosis": "Customer has 4 prior successful orders with zero dispute history. Issuing bank experienced peak load. Safe to retry.",
                "recommended": "Retry after 24h",
                "risk_score": 0.18,
                "risk_level": "LOW",
                "signals": ["4 Successful Past Orders", "Consistent IP/Device", "Zero Dispute Flags"]
            },
            "CARD_VELOCITY_EXCEEDED": {
                "name": "Aarav Mehta",
                "email": "aarav.m99@disposable-mail.io",
                "amount": 35000.0,
                "history_orders": 0,
                "error_code": "CARD_VELOCITY_EXCEEDED",
                "reason": "Velocity threshold exceeded: 4 attempts in 3 mins across different locations",
                "ai_diagnosis": "High-value anomaly with zero account tenure. Rapid card velocity detected. Automatic recovery quarantined.",
                "recommended": "Quarantine & Escalate to Human Reviewer",
                "risk_score": 0.84,
                "risk_level": "HIGH",
                "signals": ["High Value Anomaly (₹35,000)", "New Account / 0 Prior Purchases", "Velocity Spike: 4 attempts/3min"]
            },
            "MANDATE_EXHAUSTED": {
                "name": "Pooja Verma",
                "email": "pooja.verma@techcorp.in",
                "amount": 8500.0,
                "history_orders": 1,
                "error_code": "MANDATE_EXHAUSTED",
                "reason": "Mandate execution failure / Max retries (3/3) exhausted",
                "ai_diagnosis": "Automated retries reached safety limit (3/3). Requires customer re-authentication link.",
                "recommended": "Issue Smart Payment Link",
                "risk_score": 0.45,
                "risk_level": "MEDIUM",
                "signals": ["Retry Ceiling (3/3) Reached", "Recurring Mandate Expired"]
            },
            "UPI_GATEWAY_TIMEOUT": {
                "name": "Vikram Malhotra",
                "email": "vikram.m@zenith.org",
                "amount": 12400.0,
                "history_orders": 6,
                "error_code": "UPI_GATEWAY_TIMEOUT",
                "reason": "Payment Gateway Timeout on UPI Intent Resolution",
                "ai_diagnosis": "NPCI switch experienced temporary network timeout. Customer has 6 prior settlements. Safe to verify status.",
                "recommended": "Verify NPCI status & auto-retry",
                "risk_score": 0.22,
                "risk_level": "LOW",
                "signals": ["Known NPCI Switch Latency", "6 Previous Successful Orders"]
            },
            "CARD_EXPIRED": {
                "name": "Sneha Patel",
                "email": "sneha.patel@designstudio.co",
                "amount": 18900.0,
                "history_orders": 3,
                "error_code": "CARD_EXPIRED",
                "reason": "Expired Card Details on Customer Vault",
                "ai_diagnosis": "Card expired at the end of the previous month. Dispatch payment link for card update.",
                "recommended": "Dispatch Smart Payment Link",
                "risk_score": 0.15,
                "risk_level": "LOW",
                "signals": ["Card Expiry Date Reached", "Low Risk / Verified Customer"]
            }
        }

        config = scenarios.get(scenario_key, scenarios["BANK_DECLINE_TEMPORARY"])
        merchant = IngestionService.ensure_default_merchant(db)
        customer = IngestionService.get_or_create_customer(
            db=db,
            merchant_id=merchant.id,
            name=config["name"],
            email=config["email"],
            phone="+919876543210",
            history_orders=config["history_orders"]
        )

        payment_id = f"pay_sim_{uuid.uuid4().hex[:8]}"
        retry_count = 3 if scenario_key == "MANDATE_EXHAUSTED" else 0
        recovery_status = "HELD" if retry_count >= 3 else ("IN_REVIEW" if config["risk_level"] == "HIGH" else "FAILED")

        payment = Payment(
            id=payment_id,
            merchant_id=merchant.id,
            customer_id=customer.id,
            amount=config["amount"],
            currency="INR",
            status="FAILED",
            error_code=config["error_code"],
            error_description=config["reason"],
            failure_reason=config["reason"],
            ai_diagnosis=config["ai_diagnosis"],
            recommended_action=config["recommended"],
            retry_count=retry_count,
            max_retries=3,
            recovery_status=recovery_status
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)

        # Risk Assessment entry
        risk = RiskAssessment(
            id=f"risk_{uuid.uuid4().hex[:8]}",
            payment_id=payment.id,
            risk_score=config["risk_score"],
            risk_level=config["risk_level"],
            model_version="LogisticRegression-v1.0",
            signals=config["signals"],
            explanation=config["ai_diagnosis"]
        )
        db.add(risk)

        # Payment Attempt
        attempt = PaymentAttempt(
            id=f"att_{uuid.uuid4().hex[:8]}",
            payment_id=payment.id,
            attempt_number=retry_count if retry_count > 0 else 1,
            status="FAILED",
            gateway_response_code=config["error_code"],
            gateway_response_body=config["reason"],
            latency_ms=142.0
        )
        db.add(attempt)

        # Audit Event
        audit = AuditEvent(
            id=f"aud_{uuid.uuid4().hex[:8]}",
            payment_id=payment.id,
            event_type="FAILURE_INGESTED",
            actor="Failure Simulator Ingestion",
            details=f"Ingested {config['error_code']} failure for ₹{config['amount']:,.2f} ({config['name']}).",
            risk_level=config["risk_level"],
            outcome="INGESTED"
        )
        db.add(audit)
        db.commit()

        return payment

    @staticmethod
    def clear_all_payments(db: Session):
        """Clear payment records to reset feed to zero state."""
        db.query(AuditEvent).delete()
        db.query(PaymentAttempt).delete()
        db.query(RiskAssessment).delete()
        db.query(Payment).delete()
        db.commit()
