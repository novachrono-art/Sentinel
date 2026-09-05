"""
Phase 10: Human Review & Escalation Queue API
==============================================
REST endpoints for the reviewer workflow:

  POST   /api/review/quarantine/{payment_id}   - Quarantine a payment for human review
  GET    /api/review/queue                     - Paginated PENDING review queue
  GET    /api/review/{review_id}               - Full review detail + AI diagnosis
  POST   /api/review/{review_id}/decision      - Reviewer submits APPROVE / REJECT / ESCALATE
  POST   /api/review/auto-quarantine           - Batch auto-queue all HIGH-risk unreviewed payments
  GET    /api/review/stats                     - Queue depth and resolution stats

Access control:
  - Quarantine / auto-quarantine: admin or reviewer roles only
  - Queue / detail / decision:    reviewer or admin roles only
  - Merchants: cannot access this module (403)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional, Literal
import datetime

from app.database.session import get_db
from app.models.human_review import HumanReview
from app.models.payment import Payment
from app.models.audit_event import AuditEvent
from app.services.recovery.human_review_service import HumanReviewService
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

router = APIRouter(prefix="/review", tags=["Human Review & Escalation Queue"])


# ── RBAC helpers ──────────────────────────────────────────────────────────────

def _require_reviewer_or_admin(current_user: UserProfile):
    if current_user.role not in ("reviewer", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: role '{current_user.role}' cannot access the review queue.",
        )

def _reviewer_merchant_id(current_user: UserProfile) -> Optional[str]:
    """Reviewers and admins see all merchants (no scoping). Only merchant role is blocked above."""
    return None


# ── Request bodies ────────────────────────────────────────────────────────────

class QuarantineRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=512, description="Reason for quarantine")

class DecisionRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT", "ESCALATE"]
    notes: Optional[str] = Field(None, max_length=1024, description="Reviewer notes")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/quarantine/{payment_id}", status_code=status.HTTP_201_CREATED)
def quarantine_payment(
    payment_id: str,
    body: QuarantineRequest,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Quarantines a payment for human review. Sets payment.status = 'IN_REVIEW'
    and creates a HumanReview record in PENDING state.
    Idempotent: returns 200 with status='ALREADY_EXISTS' if already queued.
    """
    _require_reviewer_or_admin(current_user)
    try:
        result = HumanReviewService.quarantine_payment(
            db=db,
            payment_id=payment_id,
            reason=body.reason,
            actor=f"{current_user.role}:{current_user.email}",
        )
        return {
            "review_id": result.review_id,
            "payment_id": result.payment_id,
            "status": result.status,
            "reason": result.reason,
            "quarantined_at": result.quarantined_at,
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/queue")
def get_review_queue(
    queue_status: str = Query("PENDING", description="Filter by review status: PENDING | APPROVED | REJECTED | ESCALATED"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Returns the paginated review queue ordered oldest-first (FIFO).
    Reviewers and admins see all merchants.
    """
    _require_reviewer_or_admin(current_user)
    merchant_id = _reviewer_merchant_id(current_user)
    return HumanReviewService.get_review_queue(
        db=db,
        merchant_id=merchant_id,
        status_filter=queue_status,
        limit=limit,
        offset=offset,
    )


@router.get("/stats")
def get_queue_stats(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Returns queue depth (PENDING count), and resolution breakdown
    (approved / rejected / escalated) for the given window.
    """
    _require_reviewer_or_admin(current_user)
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    all_reviews = (
        db.query(HumanReview)
        .filter(HumanReview.quarantined_at >= since)
        .all()
    )

    pending   = sum(1 for r in all_reviews if r.status == "PENDING")
    approved  = sum(1 for r in all_reviews if r.status == "APPROVED")
    rejected  = sum(1 for r in all_reviews if r.status == "REJECTED")
    escalated = sum(1 for r in all_reviews if r.status == "ESCALATED")
    total     = len(all_reviews)
    resolved  = approved + rejected

    avg_resolution_hours: Optional[float] = None
    resolved_reviews = [
        r for r in all_reviews if r.status in ("APPROVED", "REJECTED") and r.resolved_at
    ]
    if resolved_reviews:
        durations = [
            (r.resolved_at - r.quarantined_at).total_seconds() / 3600
            for r in resolved_reviews
        ]
        avg_resolution_hours = round(sum(durations) / len(durations), 2)

    return {
        "period_days": days,
        "queue_depth": pending,
        "total_in_period": total,
        "resolution": {
            "approved": approved,
            "rejected": rejected,
            "escalated": escalated,
            "pending": pending,
        },
        "resolution_rate_pct": round(resolved / total * 100, 2) if total > 0 else 0.0,
        "avg_resolution_hours": avg_resolution_hours,
    }


@router.get("/{review_id}")
def get_review_detail(
    review_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Returns full review context: payment details, risk assessment,
    AI diagnosis, and recent audit trail.
    """
    _require_reviewer_or_admin(current_user)
    try:
        return HumanReviewService.get_review_detail(db=db, review_id=review_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{review_id}/decision")
def submit_review_decision(
    review_id: str,
    body: DecisionRequest,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Submits a reviewer decision:
      - APPROVE  → payment re-queued for automated recovery (status = FAILED)
      - REJECT   → payment frozen (status = HELD)
      - ESCALATE → remains IN_REVIEW at higher priority (status = IN_REVIEW)

    Emits a HUMAN_REVIEW_DECISION audit event.
    """
    _require_reviewer_or_admin(current_user)
    try:
        result = HumanReviewService.submit_decision(
            db=db,
            review_id=review_id,
            decision=body.decision,
            reviewer_id=current_user.id,
            notes=body.notes or "",
        )
        return {
            "review_id": result.review_id,
            "payment_id": result.payment_id,
            "decision": result.decision,
            "new_payment_status": result.new_payment_status,
            "resolved_at": result.resolved_at,
            "reviewer_id": result.reviewer_id,
            "notes": result.notes,
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/auto-quarantine", status_code=status.HTTP_200_OK)
def auto_quarantine_batch(
    merchant_id: Optional[str] = Query(None, description="Scope to a specific merchant (admin only)"),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Admin/reviewer-triggered batch: finds all unreviewed HIGH-risk or
    ambiguous-status payments and auto-queues them for review.
    Returns list of quarantine results.
    """
    _require_reviewer_or_admin(current_user)

    # Non-admin reviewers cannot scope to another merchant
    if current_user.role == "reviewer" and merchant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewers cannot scope auto-quarantine to a specific merchant.",
        )

    results = HumanReviewService.auto_quarantine_eligible(db=db, merchant_id=merchant_id)

    return {
        "quarantined_count": len(results),
        "results": [
            {
                "review_id": r.review_id,
                "payment_id": r.payment_id,
                "status": r.status,
                "reason": r.reason,
            }
            for r in results
        ],
    }
