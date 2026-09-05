"""
Phase 13: Batch Recovery Engine & Metrics REST API
==================================================
Endpoints:
  POST /api/recovery/batch/run           - Trigger a batch recovery run (live or dry-run)
  POST /api/recovery/batch/simulate-demo - Generate 100-payment benchmark demo run (is_demo=True)
  GET  /api/recovery/batch/runs          - Paginated history of batch runs
  GET  /api/recovery/batch/runs/{id}     - Detailed batch run breakdown with itemized outcomes
  GET  /api/recovery/batch/metrics       - Aggregate batch recovery KPIs across runs

Access control:
  - Merchants automatically scoped to their merchant_id
  - Reviewers / Admins have cross-merchant visibility
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any

from app.database.session import get_db
from app.services.recovery.batch_recovery_service import BatchRecoveryService
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

router = APIRouter(prefix="/recovery/batch", tags=["Batch Recovery Engine"])


# ── Pydantic Request Schemas ──────────────────────────────────────────────────

class RunBatchRequest(BaseModel):
    merchant_id: Optional[str] = Field(None, description="Target merchant ID (auto-scoped for merchant role)")
    payment_ids: Optional[List[str]] = Field(None, description="Specific payment IDs to triage")
    max_batch_size: int = Field(50, ge=1, le=200, description="Max payments to process in batch")
    dry_run: bool = Field(False, description="Simulate triage & predict outcomes without gateway calls")
    prioritization: str = Field("AMOUNT_DESC", description="Prioritization order: AMOUNT_DESC, NEWEST_FIRST, OLDEST_FIRST")


class SimulateDemoRequest(BaseModel):
    merchant_id: Optional[str] = None
    total_payments: int = Field(100, ge=10, le=500)
    target_revenue_at_risk: float = Field(250000.0, ge=1000.0)
    target_revenue_recovered: float = Field(120000.0, ge=0.0)


# ── RBAC Helpers ─────────────────────────────────────────────────────────────

def _resolve_merchant_id(current_user: UserProfile, requested_id: Optional[str]) -> Optional[str]:
    if current_user.role == "merchant":
        return current_user.merchant_id
    return requested_id


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/run", status_code=status.HTTP_201_CREATED)
def trigger_batch_recovery(
    body: RunBatchRequest,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Trigger a batch recovery run over candidate failed payments.
    - Deterministically assesses risk
    - Quarantines HIGH-risk / max-retry candidates
    - Executes guarded recovery actions on LOW/MEDIUM risk candidates
    - Emits audit events and dispatches webhooks
    """
    mid = _resolve_merchant_id(current_user, body.merchant_id)
    triggered_by = current_user.email or current_user.role

    batch_run = BatchRecoveryService.run_batch_recovery(
        db=db,
        merchant_id=mid,
        payment_ids=body.payment_ids,
        max_batch_size=body.max_batch_size,
        dry_run=body.dry_run,
        triggered_by=triggered_by,
        prioritization=body.prioritization,
    )

    return {
        "message": f"Batch run '{batch_run.id}' completed with status: {batch_run.status}.",
        "batch_id": batch_run.id,
        "status": batch_run.status,
        "is_dry_run": body.dry_run,
        "total_payments": batch_run.total_payments,
        "processed_count": batch_run.processed_count,
        "recovered_count": batch_run.recovered_count,
        "quarantined_count": batch_run.quarantined_count,
        "failed_count": batch_run.failed_count,
        "skipped_count": batch_run.skipped_count,
        "revenue_at_risk": batch_run.revenue_at_risk,
        "revenue_recovered": batch_run.revenue_recovered,
        "recovery_rate_pct": batch_run.recovery_rate,
        "escalation_rate_pct": batch_run.escalation_rate,
        "avg_attempts": batch_run.avg_attempts,
    }


@router.post("/simulate-demo", status_code=status.HTTP_201_CREATED)
def simulate_demo_batch(
    body: Optional[SimulateDemoRequest] = None,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Generate the 100-payment benchmark demo batch specified in the system design:
      100 failed payments -> INR 2,50,000 at risk -> INR 1,20,000 recovered (48% recovery rate).
    Clearly flagged with is_demo=True.
    """
    mid = _resolve_merchant_id(current_user, body.merchant_id if body else None)
    tot = body.total_payments if body else 100
    risk_rev = body.target_revenue_at_risk if body else 250000.0
    rec_rev = body.target_revenue_recovered if body else 120000.0

    demo_run = BatchRecoveryService.simulate_demo_batch(
        db=db,
        merchant_id=mid,
        total_payments=tot,
        target_revenue_at_risk=risk_rev,
        target_revenue_recovered=rec_rev,
        triggered_by=current_user.email or "DEMO_SIMULATOR",
    )

    return {
        "message": "Benchmark synthetic demo batch generated successfully.",
        "batch_id": demo_run.id,
        "is_demo": True,
        "total_payments": demo_run.total_payments,
        "revenue_at_risk": demo_run.revenue_at_risk,
        "revenue_recovered": demo_run.revenue_recovered,
        "recovery_rate_pct": demo_run.recovery_rate,
        "recovered_count": demo_run.recovered_count,
        "quarantined_count": demo_run.quarantined_count,
        "failed_count": demo_run.failed_count,
    }


@router.get("/runs")
def list_batch_runs(
    merchant_id: Optional[str] = Query(None),
    include_demo: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """List historical batch runs with pagination and merchant isolation."""
    mid = _resolve_merchant_id(current_user, merchant_id)
    return BatchRecoveryService.list_batch_runs(
        db=db,
        merchant_id=mid,
        include_demo=include_demo,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{batch_id}")
def get_batch_run_detail(
    batch_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """Retrieve detailed itemized breakdown of a single batch run."""
    mid = current_user.merchant_id if current_user.role == "merchant" else None
    detail = BatchRecoveryService.get_batch_run_detail(
        db=db,
        batch_run_id=batch_id,
        merchant_id=mid,
    )
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch run '{batch_id}' not found or access denied.",
        )
    return detail


@router.get("/metrics")
def get_batch_metrics(
    merchant_id: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    include_demo: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Get aggregate batch recovery metrics across all runs in the specified time window.
    Reports revenue at risk, revenue recovered, recovery rate %, and escalation rate.
    """
    mid = _resolve_merchant_id(current_user, merchant_id)
    return BatchRecoveryService.get_aggregate_batch_metrics(
        db=db,
        merchant_id=mid,
        days=days,
        include_demo=include_demo,
    )
