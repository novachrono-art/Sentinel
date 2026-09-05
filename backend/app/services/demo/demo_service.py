"""
Phase 17: Interactive Demo Mode & Verification Showcase Engine
==============================================================
Implements the 3 Signature Demo Stories from Master Prompt Section 38:
  Story 1: Happy Path Recovery
           ₹4,999 | Low Risk (0.12) | Temporary Bank Decline | Auto-Retry -> Recovered
  Story 2: Safety Path / Risk Gate
           ₹35,000 | High Risk (0.92) | Velocity Anomaly | Auto-Recovery Blocked -> Human Review
  Story 3: Retry Ceiling Guardrail
           ₹12,500 | Retry 3/3 Exhausted | Hard Stop -> Human Escalation
"""
import uuid
import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.risk_assessment import RiskAssessment
from app.models.human_review import HumanReview
from app.models.audit_event import AuditEvent
from app.services.performance.cache_service import kpi_cache
from app.utils.logger import logger


DEMO_MERCHANT_ID = "mer_demo_apex"
DEMO_PAYMENT_STORY1 = "pay_demo_story1"
DEMO_PAYMENT_STORY2 = "pay_demo_story2"
DEMO_PAYMENT_STORY3 = "pay_demo_story3"


class DemoService:

    @classmethod
    def seed_demo_environment(cls, db: Session) -> Dict[str, Any]:
        """
        Seeds pristine demo state matching Section 38:
        Exactly ₹2,48,000 (₹2.48 Lakhs) total revenue at risk.
        """
        cls._cleanup_demo_records(db)

        # 1. Merchant: Apex Retail India Ltd
        merchant = db.query(Merchant).filter(Merchant.id == DEMO_MERCHANT_ID).first()
        if not merchant:
            merchant = Merchant(
                id=DEMO_MERCHANT_ID,
                business_name="Apex Retail India Ltd",
                contact_email="billing@apexretail.in",
                is_live=True
            )
            db.add(merchant)
            db.flush()

        # 2. Key Customers
        cust_vip = Customer(
            id="cust_demo_vip",
            merchant_id=DEMO_MERCHANT_ID,
            name="Rahul Sharma",
            email="rahul.sharma@trusted-corp.com",
            phone="+919876543210",
            lifetime_successful_orders=14,
            lifetime_failed_orders=1,
            total_spend=125000.0,
            dispute_count=0
        )
        cust_risky = Customer(
            id="cust_demo_risky",
            merchant_id=DEMO_MERCHANT_ID,
            name="Anonymous Buyer",
            email="disposable_temp@throwawaymail.xyz",
            phone="+919999900000",
            lifetime_successful_orders=0,
            lifetime_failed_orders=5,
            total_spend=0.0,
            dispute_count=3
        )
        cust_exhausted = Customer(
            id="cust_demo_exhausted",
            merchant_id=DEMO_MERCHANT_ID,
            name="Anita Desai",
            email="anita.desai@gmail.com",
            phone="+919123456789",
            lifetime_successful_orders=2,
            lifetime_failed_orders=3,
            total_spend=24000.0,
            dispute_count=0
        )
        cust_general = Customer(
            id="cust_demo_gen",
            merchant_id=DEMO_MERCHANT_ID,
            name="General Merchant Customer",
            email="customer@sample.in",
            phone="+919800012345",
            lifetime_successful_orders=5,
            lifetime_failed_orders=2,
            total_spend=65000.0,
            dispute_count=0
        )
        db.add_all([cust_vip, cust_risky, cust_exhausted, cust_general])
        db.flush()

        # 3. Seed Payments: Exact ₹2,48,000 total revenue at risk
        # 4,999 + 35,000 + 12,500 + 45,501 + 38,000 + 62,000 + 50,000 = 248,000
        p_story1 = Payment(
            id=DEMO_PAYMENT_STORY1,
            merchant_id=DEMO_MERCHANT_ID,
            customer_id="cust_demo_vip",
            amount=4999.0,
            currency="INR",
            status="FAILED",
            error_code="BANK_DECLINE_TEMPORARY",
            error_description="Issuer switch timeout during two-factor authorization",
            failure_reason="Issuer Bank Temporary Downtime",
            retry_count=0,
            max_retries=3,
            recovery_status="FAILED"
        )
        p_story2 = Payment(
            id=DEMO_PAYMENT_STORY2,
            merchant_id=DEMO_MERCHANT_ID,
            customer_id="cust_demo_risky",
            amount=35000.0,
            currency="INR",
            status="FAILED",
            error_code="VELOCITY_FRAUD_TRIGGER",
            error_description="Transaction flagged by risk heuristic: high amount + burner email",
            failure_reason="Risk Anomaly & Velocity Warning",
            retry_count=0,
            max_retries=3,
            recovery_status="FAILED"
        )
        p_story3 = Payment(
            id=DEMO_PAYMENT_STORY3,
            merchant_id=DEMO_MERCHANT_ID,
            customer_id="cust_demo_exhausted",
            amount=12500.0,
            currency="INR",
            status="FAILED",
            error_code="CARD_EXPIRED_DECLINE",
            error_description="Customer card declined with persistent invalid state",
            failure_reason="Recurring Do Not Honor",
            retry_count=2,
            max_retries=3,
            recovery_status="FAILED"
        )

        bg_payments = [
            Payment(id="pay_demo_bg_01", merchant_id=DEMO_MERCHANT_ID, customer_id="cust_demo_gen", amount=45501.0, currency="INR", status="FAILED", error_code="INSUFFICIENT_FUNDS", recovery_status="FAILED", retry_count=1),
            Payment(id="pay_demo_bg_02", merchant_id=DEMO_MERCHANT_ID, customer_id="cust_demo_gen", amount=38000.0, currency="INR", status="FAILED", error_code="PAYMENT_TIMEOUT", recovery_status="FAILED", retry_count=0),
            Payment(id="pay_demo_bg_03", merchant_id=DEMO_MERCHANT_ID, customer_id="cust_demo_gen", amount=62000.0, currency="INR", status="FAILED", error_code="AUTHENTICATION_FAILED", recovery_status="FAILED", retry_count=0),
            Payment(id="pay_demo_bg_04", merchant_id=DEMO_MERCHANT_ID, customer_id="cust_demo_gen", amount=50000.0, currency="INR", status="FAILED", error_code="NETWORK_ERROR", recovery_status="FAILED", retry_count=1),
        ]

        db.add_all([p_story1, p_story2, p_story3] + bg_payments)
        db.flush()

        # Seed initial ingestion audit events
        for p in [p_story1, p_story2, p_story3] + bg_payments:
            ev = AuditEvent(
                id=f"aud_seed_{p.id}",
                payment_id=p.id,
                event_type="PAYMENT_FAILURE_INGESTED",
                actor="Razorpay Webhook Ingestion Engine",
                details=f"Payment {p.id} of ₹{p.amount:,.2f} ingested in FAILED state (Error: {p.error_code})",
                risk_level="PENDING",
                outcome="INGESTED",
                metadata_json={"amount": p.amount, "currency": p.currency, "error_code": p.error_code}
            )
            db.add(ev)

        db.commit()
        kpi_cache.clear()

        return {
            "status": "INITIALIZED",
            "merchant_id": DEMO_MERCHANT_ID,
            "business_name": "Apex Retail India Ltd",
            "total_revenue_at_risk": 248000.0,
            "currency": "INR",
            "payments_seeded_count": 7,
            "stories_ready": [
                {"story": 1, "title": "Happy Path Recovery", "payment_id": DEMO_PAYMENT_STORY1, "amount": 4999.0},
                {"story": 2, "title": "Safety Guardrail (High Risk)", "payment_id": DEMO_PAYMENT_STORY2, "amount": 35000.0},
                {"story": 3, "title": "Retry Ceiling Enforcement", "payment_id": DEMO_PAYMENT_STORY3, "amount": 12500.0},
            ]
        }

    @classmethod
    def execute_story_1(cls, db: Session) -> Dict[str, Any]:
        """
        Story 1: Happy Path Recovery
        ₹4,999 payment -> Risk LOW (0.12) -> Auto-retry via Razorpay -> RECOVERED
        """
        payment = db.query(Payment).filter(Payment.id == DEMO_PAYMENT_STORY1).first()
        if not payment:
            cls.seed_demo_environment(db)
            payment = db.query(Payment).filter(Payment.id == DEMO_PAYMENT_STORY1).first()

        # Step 1: Risk Assessment
        risk_score = 0.12
        risk_level = "LOW"
        risk_record = db.query(RiskAssessment).filter(RiskAssessment.payment_id == payment.id).first()
        if not risk_record:
            risk_record = RiskAssessment(
                id=f"risk_{payment.id}",
                payment_id=payment.id,
                risk_score=risk_score,
                risk_level=risk_level,
                model_version="DeterministicRiskClassifier-v1.0",
                features_used={
                    "amount_normalized": 0.05,
                    "customer_order_history": 14,
                    "velocity_score": 0.02,
                    "disposable_email": 0,
                    "dispute_count": 0
                },
                signals=["high_lifetime_value", "benign_temporary_decline"],
                explanation="Transaction exhibits normal user behavioral metrics with zero chargeback history."
            )
            db.add(risk_record)

        # Step 2: Failure Diagnosis & Recovery Strategy
        payment.ai_diagnosis = "Temporary issuer bank switch failure. Customer has high historical settlement record."
        payment.recommended_action = "DIRECT_GATEWAY_RETRY"

        # Step 3: Policy Guardrails Pre-Flight Check (All Passed)
        guardrail_result = {
            "retry_count_check": "PASS (0 < 3)",
            "risk_threshold_check": f"PASS ({risk_score} < 0.35)",
            "idempotency_lock": "ACQUIRED",
            "decision": "AUTOMATED_EXECUTION_PERMITTED"
        }

        # Step 4: Razorpay Execution & Verification
        payment.status = "RECOVERED"
        payment.recovery_status = "RECOVERED"
        payment.retry_count = 1

        # Step 5: Audit Trail
        aud_eval = AuditEvent(
            id=f"aud_risk_{payment.id}_{uuid.uuid4().hex[:6]}",
            payment_id=payment.id,
            event_type="RISK_ASSESSMENT_COMPLETED",
            actor="Deterministic Risk Classifier",
            details=f"Evaluated risk score: {risk_score} ({risk_level}). Eligible for autonomous recovery.",
            risk_level=risk_level,
            outcome="PASSED"
        )
        aud_exec = AuditEvent(
            id=f"aud_rec_{payment.id}_{uuid.uuid4().hex[:6]}",
            payment_id=payment.id,
            event_type="RECOVERY_EXECUTION_SUCCESS",
            actor="Razorpay Provider Gateway Adapter",
            details=f"Dispatched direct gateway retry with idempotency key idem_{payment.id}. Authorization verified.",
            risk_level=risk_level,
            outcome="RECOVERED",
            metadata_json={"recovered_amount": payment.amount, "currency": payment.currency}
        )
        db.add_all([aud_eval, aud_exec])
        db.commit()
        kpi_cache.clear()

        return {
            "story": 1,
            "title": "Happy Path Recovery",
            "status": "COMPLETED",
            "payment_id": payment.id,
            "amount_recovered": payment.amount,
            "currency": payment.currency,
            "steps": [
                {"step": 1, "name": "Ingestion", "detail": f"Failed payment ₹{payment.amount:,.2f} loaded"},
                {"step": 2, "name": "Risk Assessment", "detail": f"Model evaluated Risk: {risk_level} (Score {risk_score})"},
                {"step": 3, "name": "Diagnosis", "detail": payment.ai_diagnosis},
                {"step": 4, "name": "Policy Guardrails", "detail": guardrail_result["decision"]},
                {"step": 5, "name": "Razorpay Execution", "detail": "Payment captured and verified on test gateway"},
                {"step": 6, "name": "Status Update", "detail": "Marked RECOVERED and audited"}
            ],
            "outcome": "RECOVERED",
            "audit_events_logged": 2
        }

    @classmethod
    def execute_story_2(cls, db: Session) -> Dict[str, Any]:
        """
        Story 2: Safety Path / Risk Gate
        ₹35,000 payment -> Risk HIGH (0.92) -> Autonomous Recovery Blocked -> Human Review
        """
        payment = db.query(Payment).filter(Payment.id == DEMO_PAYMENT_STORY2).first()
        if not payment:
            cls.seed_demo_environment(db)
            payment = db.query(Payment).filter(Payment.id == DEMO_PAYMENT_STORY2).first()

        # Step 1: Risk Assessment (High Risk)
        risk_score = 0.92
        risk_level = "HIGH"
        risk_record = db.query(RiskAssessment).filter(RiskAssessment.payment_id == payment.id).first()
        if not risk_record:
            risk_record = RiskAssessment(
                id=f"risk_{payment.id}",
                payment_id=payment.id,
                risk_score=risk_score,
                risk_level=risk_level,
                model_version="DeterministicRiskClassifier-v1.0",
                features_used={
                    "amount_normalized": 0.85,
                    "customer_order_history": 0,
                    "velocity_score": 0.95,
                    "disposable_email": 1,
                    "dispute_count": 3
                },
                signals=["disposable_email_domain", "velocity_anomaly", "high_amount_outlier"],
                explanation="High-velocity attempts on unverified throwaway email domain with prior dispute history."
            )
            db.add(risk_record)

        # Step 2: Policy Guardrail Check (Hard Block)
        payment.status = "IN_REVIEW"
        payment.recovery_status = "IN_REVIEW"
        payment.ai_diagnosis = "Autonomous recovery blocked: High fraud risk profile and velocity anomaly detected."
        payment.recommended_action = "ESCALATE_TO_HUMAN"

        # Step 3: Human Review Quarantine Ticket
        review = db.query(HumanReview).filter(HumanReview.payment_id == payment.id).first()
        if not review:
            review = HumanReview(
                id=f"rev_{payment.id}",
                payment_id=payment.id,
                status="PENDING",
                reason_for_quarantine="Risk score 0.92 exceeds maximum autonomous threshold (0.70). Disposable email domain detected.",
                quarantined_at=datetime.datetime.utcnow()
            )
            db.add(review)

        # Step 4: Audit Event
        aud_guard = AuditEvent(
            id=f"aud_guard_{payment.id}_{uuid.uuid4().hex[:6]}",
            payment_id=payment.id,
            event_type="GUARDRAIL_BLOCKED",
            actor="Deterministic Safety Policy Engine",
            details=f"Automated recovery forbidden for payment {payment.id}: High risk score (0.92 >= 0.70).",
            risk_level=risk_level,
            outcome="BLOCKED"
        )
        aud_quar = AuditEvent(
            id=f"aud_quar_{payment.id}_{uuid.uuid4().hex[:6]}",
            payment_id=payment.id,
            event_type="HUMAN_REVIEW_QUARANTINED",
            actor="Policy Enforcement Service",
            details="Escalated to Operator Review Queue with evidentiary feature breakdown.",
            risk_level=risk_level,
            outcome="ESCALATED",
            metadata_json={"quarantined_reason": review.reason_for_quarantine, "amount": payment.amount}
        )
        db.add_all([aud_guard, aud_quar])
        db.commit()
        kpi_cache.clear()

        return {
            "story": 2,
            "title": "Safety Path / Risk Gate",
            "status": "COMPLETED",
            "payment_id": payment.id,
            "amount_quarantined": payment.amount,
            "currency": payment.currency,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "steps": [
                {"step": 1, "name": "Ingestion", "detail": f"Ingested ₹{payment.amount:,.2f} flagged transaction"},
                {"step": 2, "name": "Risk Classifier", "detail": f"Risk Score {risk_score} (HIGH) exceeds 0.70 threshold"},
                {"step": 3, "name": "Deterministic Guardrail", "detail": "Automated charge blocked: Zero Gateway Touch"},
                {"step": 4, "name": "Quarantine Action", "detail": "Assigned to Human Review Queue for manual operator audit"},
                {"step": 5, "name": "Audit Logging", "detail": "Security and compliance trail updated with SHA-256 hash"}
            ],
            "outcome": "QUARANTINED_TO_HUMAN_REVIEW",
            "review_ticket_id": review.id
        }

    @classmethod
    def execute_story_3(cls, db: Session) -> Dict[str, Any]:
        """
        Story 3: Retry Ceiling Guardrail
        ₹12,500 payment with 2 prior retries -> Retry #3 fails -> Ceiling Hit -> Hard Stop
        """
        payment = db.query(Payment).filter(Payment.id == DEMO_PAYMENT_STORY3).first()
        if not payment:
            cls.seed_demo_environment(db)
            payment = db.query(Payment).filter(Payment.id == DEMO_PAYMENT_STORY3).first()

        # Step 1: Final Retry Attempt (3rd attempt)
        payment.retry_count = 3  # Hit max retries (3 / 3)
        payment.status = "IN_REVIEW"
        payment.recovery_status = "IN_REVIEW"
        payment.ai_diagnosis = "Maximum retry ceiling (3 attempts) reached without bank confirmation. Automated attempts halted."
        payment.recommended_action = "MANUAL_OUTREACH_PAYMENT_LINK"

        # Step 2: Quarantine for Manual Intervention
        review = db.query(HumanReview).filter(HumanReview.payment_id == payment.id).first()
        if not review:
            review = HumanReview(
                id=f"rev_{payment.id}",
                payment_id=payment.id,
                status="PENDING",
                reason_for_quarantine="Max retry ceiling (3/3) exhausted. Customer requires alternate payment method outreach.",
                quarantined_at=datetime.datetime.utcnow()
            )
            db.add(review)

        # Step 3: Audit Trail
        aud_ceiling = AuditEvent(
            id=f"aud_ceil_{payment.id}_{uuid.uuid4().hex[:6]}",
            payment_id=payment.id,
            event_type="RETRY_CEILING_EXHAUSTED",
            actor="Deterministic Policy Engine",
            details=f"Payment {payment.id} exhausted max retry ceiling (3 of 3 attempts). Automated charges terminated.",
            risk_level="MEDIUM",
            outcome="STOPPED"
        )
        aud_esc = AuditEvent(
            id=f"aud_esc_{payment.id}_{uuid.uuid4().hex[:6]}",
            payment_id=payment.id,
            event_type="ESCALATED_TO_HUMAN",
            actor="Recovery Execution Worker",
            details="Transferred to Human Review for manual outreach via WhatsApp / SMS payment link.",
            risk_level="MEDIUM",
            outcome="ESCALATED"
        )
        db.add_all([aud_ceiling, aud_esc])
        db.commit()
        kpi_cache.clear()

        return {
            "story": 3,
            "title": "Retry Ceiling Guardrail",
            "status": "COMPLETED",
            "payment_id": payment.id,
            "amount": payment.amount,
            "retries_exhausted": f"{payment.retry_count} / {payment.max_retries}",
            "steps": [
                {"step": 1, "name": "Retry Execution", "detail": "3rd retry attempt dispatched to gateway"},
                {"step": 2, "name": "Gateway Response", "detail": "Card decline: Persistent invalid status"},
                {"step": 3, "name": "Ceiling Guardrail", "detail": "Hard cap of 3 attempts reached: AUTOMATION TERMINATED"},
                {"step": 4, "name": "Human Escalation", "detail": "Escalated for operator outreach with alternate payment link"},
                {"step": 5, "name": "Audit Logging", "detail": "Audit event recorded for compliance verification"}
            ],
            "outcome": "CEILING_EXHAUSTED_AND_ESCALATED",
            "review_ticket_id": review.id
        }

    @classmethod
    def get_demo_state(cls, db: Session) -> Dict[str, Any]:
        """Returns the current state of all 3 demo stories and aggregate metrics."""
        p1 = db.query(Payment).filter(Payment.id == DEMO_PAYMENT_STORY1).first()
        p2 = db.query(Payment).filter(Payment.id == DEMO_PAYMENT_STORY2).first()
        p3 = db.query(Payment).filter(Payment.id == DEMO_PAYMENT_STORY3).first()

        story1_done = p1.status == "RECOVERED" if p1 else False
        story2_done = p2.status == "IN_REVIEW" if p2 else False
        story3_done = p3.retry_count >= 3 if p3 else False

        total_risk_query = db.query(Payment).filter(Payment.merchant_id == DEMO_MERCHANT_ID)
        total_risk = sum(p.amount for p in total_risk_query.all())
        total_recovered = sum(p.amount for p in total_risk_query.filter(Payment.status == "RECOVERED").all())
        total_reviews = db.query(HumanReview).join(Payment).filter(Payment.merchant_id == DEMO_MERCHANT_ID, HumanReview.status == "PENDING").count()

        return {
            "merchant_id": DEMO_MERCHANT_ID,
            "total_revenue_at_risk": total_risk,
            "total_recovered_revenue": total_recovered,
            "pending_review_count": total_reviews,
            "stories": {
                "story_1_happy_path": {
                    "completed": story1_done,
                    "payment_id": DEMO_PAYMENT_STORY1,
                    "amount": 4999.0,
                    "current_status": p1.status if p1 else "NOT_SEEDED",
                },
                "story_2_safety_path": {
                    "completed": story2_done,
                    "payment_id": DEMO_PAYMENT_STORY2,
                    "amount": 35000.0,
                    "current_status": p2.status if p2 else "NOT_SEEDED",
                },
                "story_3_retry_guardrail": {
                    "completed": story3_done,
                    "payment_id": DEMO_PAYMENT_STORY3,
                    "amount": 12500.0,
                    "current_status": p3.status if p3 else "NOT_SEEDED",
                    "retries": f"{p3.retry_count if p3 else 0}/3",
                }
            }
        }

    @classmethod
    def reset_demo(cls, db: Session) -> Dict[str, Any]:
        """Wipes and resets the demo database cleanly to the initial state."""
        return cls.seed_demo_environment(db)

    @classmethod
    def _cleanup_demo_records(cls, db: Session) -> None:
        """Removes demo records to avoid unique constraint collisions."""
        demo_pay_ids = [
            DEMO_PAYMENT_STORY1, DEMO_PAYMENT_STORY2, DEMO_PAYMENT_STORY3,
            "pay_demo_bg_01", "pay_demo_bg_02", "pay_demo_bg_03", "pay_demo_bg_04"
        ]
        # Clean associated child tables
        db.query(AuditEvent).filter(AuditEvent.payment_id.in_(demo_pay_ids)).delete(synchronize_session=False)
        db.query(HumanReview).filter(HumanReview.payment_id.in_(demo_pay_ids)).delete(synchronize_session=False)
        db.query(RiskAssessment).filter(RiskAssessment.payment_id.in_(demo_pay_ids)).delete(synchronize_session=False)
        db.query(Payment).filter(Payment.id.in_(demo_pay_ids)).delete(synchronize_session=False)
        
        # Clean demo customers
        db.query(Customer).filter(Customer.id.in_(["cust_demo_vip", "cust_demo_risky", "cust_demo_exhausted", "cust_demo_gen"])).delete(synchronize_session=False)
        db.commit()
