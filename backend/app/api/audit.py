"""
Phase 12: Audit Trail & Compliance Export API
==============================================
REST endpoints for the compliance & audit module:

  GET  /api/audit/events                    - Paginated, filterable audit log
  GET  /api/audit/events/{payment_id}       - Full chronological timeline for a payment
  GET  /api/audit/export/csv                - CSV export (streaming response)
  GET  /api/audit/export/ndjson             - NDJSON export (streaming response)
  GET  /api/audit/chain                     - Compute tamper-evident SHA-256 chain hash
  GET  /api/audit/compliance-report         - Aggregate compliance KPI report
  POST /api/audit/events                    - Manually emit a custom audit event (admin only)

Access control:
  - Merchant role: scoped to their own merchant_id (read-only)
  - Reviewer / admin: full access across all merchants
  - Export and chain endpoints: reviewer / admin only
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional
import datetime
import uuid
import io

from app.database.session import get_db
from app.models.audit_event import AuditEvent
from app.models.payment import Payment
from app.services.audit import audit_service
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

router = APIRouter(prefix="/audit", tags=["Audit Trail & Compliance"])


# ── RBAC ─────────────────────────────────────────────────────────────────────

def _resolve_merchant_id(current_user: UserProfile,
                          requested_merchant_id: Optional[str] = None) -> Optional[str]:
    """Merchants are always scoped to their own ID. Admins/reviewers pass through."""
    if current_user.role == "merchant":
        return current_user.merchant_id
    return requested_merchant_id


def _require_staff(current_user: UserProfile):
    """Only reviewer or admin roles can access export / chain / write endpoints."""
    if current_user.role == "merchant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Audit exports and chain verification are restricted to reviewer/admin roles.",
        )


# ── Request body ──────────────────────────────────────────────────────────────

class EmitEventRequest(BaseModel):
    payment_id: str = Field(..., description="Payment this event belongs to")
    event_type: str = Field(..., min_length=3, max_length=64)
    actor: str = Field(..., min_length=2, max_length=64)
    details: str = Field(..., min_length=5, max_length=2048)
    outcome: Optional[str] = Field(None, max_length=32)
    risk_level: Optional[str] = Field(None, pattern="^(LOW|MEDIUM|HIGH)$")
    metadata_json: Optional[dict] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/events")
def list_audit_events(
    merchant_id: Optional[str] = Query(None),
    payment_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    since: Optional[datetime.datetime] = Query(None, description="ISO-8601 UTC datetime"),
    until: Optional[datetime.datetime] = Query(None, description="ISO-8601 UTC datetime"),
    search: Optional[str] = Query(None, description="Full-text search on details and actor"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Returns paginated audit events with multi-field filtering.
    Merchants see only their own events. Admins/reviewers see all.
    """
    mid = _resolve_merchant_id(current_user, merchant_id)
    return audit_service.query_events(
        db=db,
        merchant_id=mid,
        payment_id=payment_id,
        event_type=event_type,
        actor=actor,
        outcome=outcome,
        risk_level=risk_level,
        since=since,
        until=until,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/events/{payment_id}")
def get_payment_audit_timeline(
    payment_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Returns the complete chronological audit trail for a single payment,
    with per-event chain hashes for tamper detection.
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Payment '{payment_id}' not found.")

    # Merchant scope check
    if (current_user.role == "merchant"
            and payment.merchant_id != current_user.merchant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Access denied to this payment's audit trail.")

    return audit_service.get_payment_timeline(db=db, payment_id=payment_id)


@router.get("/export/csv")
def export_audit_csv(
    merchant_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    since: Optional[datetime.datetime] = Query(None),
    until: Optional[datetime.datetime] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Streams a CSV file of audit events for the given filters.
    Restricted to reviewer / admin roles.
    """
    _require_staff(current_user)
    mid = _resolve_merchant_id(current_user, merchant_id)
    csv_content = audit_service.export_csv(
        db=db, merchant_id=mid, since=since, until=until, event_type=event_type
    )

    filename = f"audit_export_{datetime.date.today().isoformat()}.csv"
    return StreamingResponse(
        io.StringIO(csv_content),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/ndjson")
def export_audit_ndjson(
    merchant_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    since: Optional[datetime.datetime] = Query(None),
    until: Optional[datetime.datetime] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Streams a newline-delimited JSON file (NDJSON) of audit events.
    One JSON object per line — compatible with BigQuery, Elasticsearch, etc.
    Restricted to reviewer / admin roles.
    """
    _require_staff(current_user)
    mid = _resolve_merchant_id(current_user, merchant_id)
    ndjson_content = audit_service.export_ndjson(
        db=db, merchant_id=mid, since=since, until=until, event_type=event_type
    )

    filename = f"audit_export_{datetime.date.today().isoformat()}.ndjson"
    return StreamingResponse(
        io.StringIO(ndjson_content),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/chain")
def get_chain_hash(
    merchant_id: Optional[str] = Query(None),
    since: Optional[datetime.datetime] = Query(None),
    until: Optional[datetime.datetime] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Computes and returns the tamper-evident SHA-256 hash chain over all
    audit events in the specified window.

    The final_chain_hash uniquely fingerprints the entire ordered event sequence.
    Any modification, deletion, or insertion of events in that window will produce
    a different hash — enabling compliance-grade tamper detection.
    """
    _require_staff(current_user)
    mid = _resolve_merchant_id(current_user, merchant_id)
    return audit_service.compute_chain_hash(db=db, merchant_id=mid, since=since, until=until)


@router.get("/compliance-report")
def get_compliance_report(
    merchant_id: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Returns a compliance KPI report covering:
      - Total audit event count and breakdown by type / actor / outcome
      - Human review coverage rate for HIGH-risk payments
      - Data integrity chain hash for the period
    """
    _require_staff(current_user)
    mid = _resolve_merchant_id(current_user, merchant_id)
    return audit_service.compliance_report(db=db, merchant_id=mid, days=days)


@router.post("/events", status_code=status.HTTP_201_CREATED)
def emit_custom_audit_event(
    body: EmitEventRequest,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Admin-only: manually emit a custom audit event (e.g. compliance notes,
    manual interventions, system annotations). These are stored with
    actor set to the current user's email for traceability.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin users can manually emit audit events.",
        )

    payment = db.query(Payment).filter(Payment.id == body.payment_id).first()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment '{body.payment_id}' not found.",
        )

    event = AuditEvent(
        id=f"ae_{uuid.uuid4().hex[:16]}",
        payment_id=body.payment_id,
        event_type=body.event_type,
        actor=f"ManualEntry:{current_user.email}",
        details=body.details,
        outcome=body.outcome,
        risk_level=body.risk_level,
        metadata_json=body.metadata_json,
        timestamp=datetime.datetime.utcnow(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    return {
        "id": event.id,
        "payment_id": event.payment_id,
        "event_type": event.event_type,
        "actor": event.actor,
        "timestamp": event.timestamp.isoformat(),
    }
