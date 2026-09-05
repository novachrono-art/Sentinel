"""
Phase 10: Human Review & Escalation Queue Service
===================================================
Handles the full reviewer workflow for high-risk or ambiguous payments:

  1. quarantine_payment()     - Move a HIGH-risk or policy-blocked payment into PENDING review
  2. get_review_queue()       - List all PENDING reviews (paginated, oldest-first)
  3. get_review_detail()      - Full context for a single review (payment + risk + diagnosis)
  4. submit_decision()        - Reviewer submits APPROVE / REJECT / ESCALATE with notes
  5. auto_quarantine_eligible() - Find payments that should be auto-queued (batch helper)

Audit events are emitted for every state transition.
"""
import uuid
import datetime
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.human_review import HumanReview
from app.models.risk_assessment import RiskAssessment
from app.models.audit_event import AuditEvent
from app.services.recovery.diagnosis_service import DiagnosisService
from app.utils.logger import logger


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class QuarantineResult:
    review_id: str
    payment_id: str
    status: str               # "CREATED" | "ALREADY_EXISTS"
    reason: str
    quarantined_at: str


@dataclass
class ReviewDecisionResult:
    review_id: str
    payment_id: str
    decision: str             # "APPROVE" | "REJECT" | "ESCALATE"
    new_payment_status: str
    resolved_at: str
    reviewer_id: Optional[str]
    notes: str


# ── Constants ─────────────────────────────────────────────────────────────────

# Payments in these statuses are NOT eligible for re-quarantine
TERMINAL_STATUSES = {"CAPTURED", "RECOVERED", "CANCELLED"}

# Payment statuses that imply ambiguity needing human eyes
AMBIGUOUS_STATUSES = {"PROCESSING", "PENDING_VERIFICATION"}


class HumanReviewService:
    """
    Stateless service class for the human review & escalation queue.
    All methods accept a SQLAlchemy Session and operate transactionally.
    """

    # ── 1. Quarantine ──────────────────────────────────────────────────────────

    @classmethod
    def quarantine_payment(
        cls,
        db: Session,
        payment_id: str,
        reason: str,
        actor: str = "AI_AGENT",
    ) -> QuarantineResult:
        """
        Moves a payment into the PENDING human review queue.
        Idempotent: returns ALREADY_EXISTS if the payment is already queued.
        Also sets payment.status = 'IN_REVIEW'.
        """
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            raise ValueError(f"Payment '{payment_id}' not found.")

        if payment.status in TERMINAL_STATUSES:
            raise ValueError(
                f"Cannot quarantine payment '{payment_id}': terminal status '{payment.status}'."
            )

        # Idempotency check
        existing = db.query(HumanReview).filter(HumanReview.payment_id == payment_id).first()
        if existing and existing.status == "PENDING":
            logger.info(f"[HumanReview] Payment {payment_id} already PENDING review {existing.id}")
            return QuarantineResult(
                review_id=existing.id,
                payment_id=payment_id,
                status="ALREADY_EXISTS",
                reason=existing.reason_for_quarantine,
                quarantined_at=existing.quarantined_at.isoformat(),
            )

        review_id = f"rev_{uuid.uuid4().hex[:16]}"
        now = datetime.datetime.utcnow()

        review = HumanReview(
            id=review_id,
            payment_id=payment_id,
            status="PENDING",
            reason_for_quarantine=reason,
            quarantined_at=now,
        )
        db.add(review)

        # Update payment status
        payment.status = "IN_REVIEW"

        # Emit audit event
        db.add(AuditEvent(
            id=f"ae_{uuid.uuid4().hex[:16]}",
            payment_id=payment_id,
            event_type="HUMAN_REVIEW_QUARANTINE",
            actor=actor,
            details=f"Payment quarantined for human review. Reason: {reason}",
            risk_level=None,
            outcome="PENDING",
            metadata_json={"review_id": review_id},
            timestamp=now,
        ))

        db.commit()
        logger.info(f"[HumanReview] Quarantined {payment_id} -> review {review_id}")

        return QuarantineResult(
            review_id=review_id,
            payment_id=payment_id,
            status="CREATED",
            reason=reason,
            quarantined_at=now.isoformat(),
        )

    # ── 2. Review Queue ────────────────────────────────────────────────────────

    @classmethod
    def get_review_queue(
        cls,
        db: Session,
        merchant_id: Optional[str] = None,
        status_filter: str = "PENDING",
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Returns paginated list of HumanReview records, oldest-first (FIFO queue).
        Optionally filtered by merchant and status.
        """
        q = (
            db.query(HumanReview)
            .join(Payment, Payment.id == HumanReview.payment_id)
            .filter(HumanReview.status == status_filter)
            .order_by(HumanReview.quarantined_at.asc())
        )
        if merchant_id:
            q = q.filter(Payment.merchant_id == merchant_id)

        total = q.count()
        reviews = q.offset(offset).limit(limit).all()

        items = []
        for rev in reviews:
            payment = db.query(Payment).filter(Payment.id == rev.payment_id).first()
            risk = (
                db.query(RiskAssessment)
                .filter(RiskAssessment.payment_id == rev.payment_id)
                .first()
            )
            items.append({
                "review_id": rev.id,
                "payment_id": rev.payment_id,
                "status": rev.status,
                "reason_for_quarantine": rev.reason_for_quarantine,
                "quarantined_at": rev.quarantined_at.isoformat(),
                "resolved_at": rev.resolved_at.isoformat() if rev.resolved_at else None,
                "payment": {
                    "amount": payment.amount if payment else None,
                    "currency": payment.currency if payment else "INR",
                    "error_code": payment.error_code if payment else None,
                    "merchant_id": payment.merchant_id if payment else None,
                    "retry_count": payment.retry_count if payment else 0,
                },
                "risk": {
                    "risk_score": float(risk.risk_score) if risk else None,
                    "risk_level": risk.risk_level if risk else None,
                } if risk else None,
            })

        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": items,
        }

    # ── 3. Review Detail ───────────────────────────────────────────────────────

    @classmethod
    def get_review_detail(
        cls, db: Session, review_id: str
    ) -> Dict[str, Any]:
        """
        Returns comprehensive context for a single review:
        payment info, risk assessment, AI diagnosis, and existing decision.
        """
        review = db.query(HumanReview).filter(HumanReview.id == review_id).first()
        if not review:
            raise ValueError(f"Review '{review_id}' not found.")

        payment = db.query(Payment).filter(Payment.id == review.payment_id).first()
        risk = (
            db.query(RiskAssessment)
            .filter(RiskAssessment.payment_id == review.payment_id)
            .first()
        )

        # Run fresh diagnosis for reviewer context (read-only, no DB writes)
        diagnosis = DiagnosisService.diagnose(payment) if payment else None

        # Last 5 audit events for context
        audit_events = (
            db.query(AuditEvent)
            .filter(AuditEvent.payment_id == review.payment_id)
            .order_by(AuditEvent.timestamp.desc())
            .limit(5)
            .all()
        )

        return {
            "review": {
                "id": review.id,
                "status": review.status,
                "reason_for_quarantine": review.reason_for_quarantine,
                "decision": review.decision,
                "decision_notes": review.decision_notes,
                "reviewer_id": review.reviewer_id,
                "quarantined_at": review.quarantined_at.isoformat(),
                "resolved_at": review.resolved_at.isoformat() if review.resolved_at else None,
            },
            "payment": {
                "id": payment.id,
                "amount": payment.amount,
                "currency": payment.currency,
                "status": payment.status,
                "error_code": payment.error_code,
                "error_description": payment.error_description,
                "failure_reason": payment.failure_reason,
                "retry_count": payment.retry_count,
                "max_retries": payment.max_retries,
                "merchant_id": payment.merchant_id,
                "customer_id": payment.customer_id,
                "created_at": payment.created_at.isoformat(),
            } if payment else None,
            "risk_assessment": {
                "risk_score": float(risk.risk_score),
                "risk_level": risk.risk_level,
                "signals": risk.signals or [],
                "features_used": risk.features_used or {},
                "model_version": risk.model_version,
                "evaluated_at": risk.evaluated_at.isoformat(),
            } if risk else None,
            "ai_diagnosis": {
                "category": diagnosis.category,
                "situation": diagnosis.situation,
                "root_cause": diagnosis.root_cause,
                "recommended_action": diagnosis.recommended_action,
                "confidence": diagnosis.confidence,
                "recovery_probability": diagnosis.recovery_probability,
                "customer_message": diagnosis.customer_message,
                "merchant_explanation": diagnosis.merchant_explanation,
            } if diagnosis else None,
            "recent_audit_events": [
                {
                    "event_type": ae.event_type,
                    "actor": ae.actor,
                    "details": ae.details,
                    "outcome": ae.outcome,
                    "timestamp": ae.timestamp.isoformat(),
                }
                for ae in audit_events
            ],
        }

    # ── 4. Submit Reviewer Decision ────────────────────────────────────────────

    @classmethod
    def submit_decision(
        cls,
        db: Session,
        review_id: str,
        decision: str,              # "APPROVE" | "REJECT" | "ESCALATE"
        reviewer_id: str,
        notes: str = "",
    ) -> ReviewDecisionResult:
        """
        Reviewer submits a decision on a PENDING human review.
        - APPROVE  → payment.status = 'FAILED' (re-queued for automated retry)
        - REJECT   → payment.status = 'HELD'   (frozen, no further automated action)
        - ESCALATE → payment.status = 'IN_REVIEW', review.status = 'ESCALATED'

        Emits an audit event for every decision.
        """
        valid_decisions = {"APPROVE", "REJECT", "ESCALATE"}
        if decision not in valid_decisions:
            raise ValueError(f"Invalid decision '{decision}'. Must be one of {valid_decisions}.")

        review = db.query(HumanReview).filter(HumanReview.id == review_id).first()
        if not review:
            raise ValueError(f"Review '{review_id}' not found.")
        if review.status != "PENDING":
            raise ValueError(
                f"Review '{review_id}' is already resolved (status='{review.status}'). "
                "Cannot re-submit a decision."
            )

        payment = db.query(Payment).filter(Payment.id == review.payment_id).first()
        now = datetime.datetime.utcnow()

        # Map decision → new payment status
        status_map = {
            "APPROVE": "FAILED",      # AI agent picks it back up for automated recovery
            "REJECT": "HELD",         # Frozen – no further automated action
            "ESCALATE": "IN_REVIEW",  # Stays in review, escalated priority
        }
        review_status_map = {
            "APPROVE": "APPROVED",
            "REJECT": "REJECTED",
            "ESCALATE": "ESCALATED",
        }

        new_payment_status = status_map[decision]
        new_review_status = review_status_map[decision]

        # Update review record
        review.decision = decision
        review.decision_notes = notes
        review.reviewer_id = reviewer_id
        review.status = new_review_status
        review.resolved_at = now if decision != "ESCALATE" else None

        # Update payment
        payment.status = new_payment_status

        # Emit audit event
        db.add(AuditEvent(
            id=f"ae_{uuid.uuid4().hex[:16]}",
            payment_id=review.payment_id,
            event_type="HUMAN_REVIEW_DECISION",
            actor=f"Reviewer:{reviewer_id}",
            details=(
                f"Human reviewer submitted decision: {decision}. "
                f"Notes: {notes or 'None'}. "
                f"Payment status → {new_payment_status}."
            ),
            risk_level=None,
            outcome=decision,
            metadata_json={
                "review_id": review_id,
                "reviewer_id": reviewer_id,
                "decision": decision,
                "new_payment_status": new_payment_status,
            },
            timestamp=now,
        ))

        db.commit()
        logger.info(
            f"[HumanReview] Review {review_id}: decision={decision} by {reviewer_id}. "
            f"Payment {review.payment_id} -> {new_payment_status}"
        )

        return ReviewDecisionResult(
            review_id=review_id,
            payment_id=review.payment_id,
            decision=decision,
            new_payment_status=new_payment_status,
            resolved_at=now.isoformat(),
            reviewer_id=reviewer_id,
            notes=notes,
        )

    # ── 5. Auto-Quarantine Batch Helper ───────────────────────────────────────

    @classmethod
    def auto_quarantine_eligible(
        cls, db: Session, merchant_id: Optional[str] = None
    ) -> List[QuarantineResult]:
        """
        Scans FAILED payments that have HIGH risk or ambiguous status and
        auto-queues them for human review if not already queued.
        Returns a list of QuarantineResult for each payment processed.
        """
        q = (
            db.query(Payment)
            .outerjoin(RiskAssessment, RiskAssessment.payment_id == Payment.id)
            .outerjoin(HumanReview, HumanReview.payment_id == Payment.id)
            .filter(
                Payment.status.in_(["FAILED"] + list(AMBIGUOUS_STATUSES)),
                HumanReview.id.is_(None),  # not already in review
            )
        )
        if merchant_id:
            q = q.filter(Payment.merchant_id == merchant_id)

        candidates = q.all()
        results: List[QuarantineResult] = []

        for payment in candidates:
            risk = (
                db.query(RiskAssessment)
                .filter(RiskAssessment.payment_id == payment.id)
                .first()
            )
            risk_level = risk.risk_level if risk else "UNKNOWN"

            if risk_level == "HIGH" or payment.status in AMBIGUOUS_STATUSES:
                reason = (
                    f"Auto-quarantine: risk_level={risk_level}, "
                    f"payment_status={payment.status}, "
                    f"error_code={payment.error_code}"
                )
                try:
                    result = cls.quarantine_payment(
                        db=db,
                        payment_id=payment.id,
                        reason=reason,
                        actor="AUTO_QUARANTINE_BATCH",
                    )
                    results.append(result)
                except ValueError as e:
                    logger.warning(f"[AutoQuarantine] Skipped {payment.id}: {e}")

        return results
