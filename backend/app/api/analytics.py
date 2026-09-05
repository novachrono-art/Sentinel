"""
Phase 9: Analytics & Merchant Dashboard API
============================================
Provides real-time KPI aggregations for the merchant dashboard:
  - Revenue recovery rate and recovered amount
  - Failure pattern breakdown by error code
  - Risk distribution (LOW / MEDIUM / HIGH)
  - Recovery action success rates by action type
  - 7-day rolling daily trend for failures vs. recoveries
  - Top customers by risk exposure
  - Per-merchant isolated views (merchant role) vs. admin global views
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_
from typing import Optional, List, Dict, Any
import datetime

from app.database.session import get_db
from app.models.payment import Payment
from app.models.recovery_action import RecoveryAction
from app.models.risk_assessment import RiskAssessment
from app.models.customer import Customer
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

router = APIRouter(prefix="/analytics", tags=["Analytics & Dashboard"])


def _merchant_filter(current_user: UserProfile):
    """Return the merchant_id to filter on, or None for admins (global view)."""
    if current_user.role == "merchant" and current_user.merchant_id:
        return current_user.merchant_id
    return None


# ---------------------------------------------------------------------------
# 1. Revenue Recovery KPI Summary
# ---------------------------------------------------------------------------
@router.get("/summary")
def get_recovery_summary(
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Returns the headline KPIs for the merchant dashboard:
      - total_failed_payments, total_failed_value
      - total_recovered_payments, total_recovered_value
      - recovery_rate (%), revenue_recovery_rate (%)
      - average_risk_score, high_risk_count
      - pending_review_count
    """
    mid = _merchant_filter(current_user)
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    base_q = db.query(Payment).filter(Payment.created_at >= since)
    if mid:
        base_q = base_q.filter(Payment.merchant_id == mid)

    all_payments = base_q.all()

    failed = [p for p in all_payments if p.status == "FAILED"]
    recovered = [p for p in all_payments if p.status == "RECOVERED"]
    review = [p for p in all_payments if p.status == "IN_REVIEW"]

    total_failed_value = sum(p.amount or 0 for p in failed)
    total_recovered_value = sum(p.amount or 0 for p in recovered)

    total_failed_count = len(failed)
    total_recovered_count = len(recovered)
    total_count = len(all_payments)

    recovery_rate = round(
        (total_recovered_count / total_failed_count * 100) if total_failed_count > 0 else 0.0, 2
    )
    revenue_recovery_rate = round(
        (total_recovered_value / total_failed_value * 100) if total_failed_value > 0 else 0.0, 2
    )

    # Risk aggregation from risk_assessments
    risk_q = (
        db.query(
            func.avg(RiskAssessment.risk_score).label("avg_score"),
            func.sum(case((RiskAssessment.risk_level == "HIGH", 1), else_=0)).label("high_count"),
        )
        .join(Payment, Payment.id == RiskAssessment.payment_id)
        .filter(Payment.created_at >= since)
    )
    if mid:
        risk_q = risk_q.filter(Payment.merchant_id == mid)
    risk_row = risk_q.first()

    return {
        "period_days": days,
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "payments": {
            "total": total_count,
            "failed": total_failed_count,
            "recovered": total_recovered_count,
            "pending_review": len(review),
        },
        "revenue": {
            "total_failed_value_inr": round(total_failed_value, 2),
            "total_recovered_value_inr": round(total_recovered_value, 2),
            "net_at_risk_inr": round(total_failed_value - total_recovered_value, 2),
        },
        "rates": {
            "payment_recovery_rate_pct": recovery_rate,
            "revenue_recovery_rate_pct": revenue_recovery_rate,
        },
        "risk": {
            "average_risk_score": round(float(risk_row.avg_score or 0), 4),
            "high_risk_payment_count": int(risk_row.high_count or 0),
        },
    }


# ---------------------------------------------------------------------------
# 2. Failure Pattern Breakdown (by error code)
# ---------------------------------------------------------------------------
@router.get("/failure-breakdown")
def get_failure_breakdown(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Groups failed payments by error_code and returns count + total value.
    Useful for understanding which failure modes dominate.
    """
    mid = _merchant_filter(current_user)
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    q = (
        db.query(
            Payment.error_code,
            func.count(Payment.id).label("count"),
            func.sum(Payment.amount).label("total_value"),
        )
        .filter(Payment.created_at >= since, Payment.status == "FAILED")
    )
    if mid:
        q = q.filter(Payment.merchant_id == mid)

    rows = q.group_by(Payment.error_code).order_by(func.count(Payment.id).desc()).all()

    return {
        "period_days": days,
        "breakdown": [
            {
                "error_code": row.error_code or "UNKNOWN",
                "count": row.count,
                "total_value_inr": round(float(row.total_value or 0), 2),
            }
            for row in rows
        ],
    }


# ---------------------------------------------------------------------------
# 3. Risk Distribution
# ---------------------------------------------------------------------------
@router.get("/risk-distribution")
def get_risk_distribution(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Returns count of payments in each risk bucket (LOW / MEDIUM / HIGH)
    and their average risk scores.
    """
    mid = _merchant_filter(current_user)
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    q = (
        db.query(
            RiskAssessment.risk_level,
            func.count(RiskAssessment.id).label("count"),
            func.avg(RiskAssessment.risk_score).label("avg_score"),
        )
        .join(Payment, Payment.id == RiskAssessment.payment_id)
        .filter(Payment.created_at >= since)
    )
    if mid:
        q = q.filter(Payment.merchant_id == mid)

    rows = q.group_by(RiskAssessment.risk_level).all()

    total = sum(r.count for r in rows) or 1
    return {
        "period_days": days,
        "distribution": [
            {
                "risk_level": row.risk_level,
                "count": row.count,
                "percentage": round(row.count / total * 100, 2),
                "average_score": round(float(row.avg_score or 0), 4),
            }
            for row in rows
        ],
    }


# ---------------------------------------------------------------------------
# 4. Recovery Action Success Rate by Action Type
# ---------------------------------------------------------------------------
@router.get("/action-performance")
def get_action_performance(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Groups RecoveryActions by type and shows execution success vs. failure counts.
    Helps merchants understand which recovery strategies work best.
    """
    mid = _merchant_filter(current_user)
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    q = (
        db.query(
            RecoveryAction.action_type,
            func.count(RecoveryAction.id).label("total"),
            func.sum(case((RecoveryAction.status == "EXECUTED", 1), else_=0)).label("succeeded"),
            func.sum(case((RecoveryAction.status == "FAILED", 1), else_=0)).label("failed"),
            func.sum(case((RecoveryAction.status == "BLOCKED", 1), else_=0)).label("blocked"),
        )
        .join(Payment, Payment.id == RecoveryAction.payment_id)
        .filter(RecoveryAction.executed_at >= since)
    )
    if mid:
        q = q.filter(Payment.merchant_id == mid)

    rows = q.group_by(RecoveryAction.action_type).order_by(func.count(RecoveryAction.id).desc()).all()

    return {
        "period_days": days,
        "action_performance": [
            {
                "action_type": row.action_type,
                "total_executed": row.total,
                "succeeded": int(row.succeeded or 0),
                "failed": int(row.failed or 0),
                "blocked": int(row.blocked or 0),
                "success_rate_pct": round(
                    (int(row.succeeded or 0) / row.total * 100) if row.total > 0 else 0.0, 2
                ),
            }
            for row in rows
        ],
    }


# ---------------------------------------------------------------------------
# 5. Daily Trend (7-day rolling window)
# ---------------------------------------------------------------------------
@router.get("/daily-trend")
def get_daily_trend(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Returns day-by-day breakdown of:
      - failed_count, failed_value
      - recovered_count, recovered_value
    Useful for plotting the recovery trend chart.
    """
    mid = _merchant_filter(current_user)
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    base_q = db.query(Payment).filter(Payment.created_at >= since)
    if mid:
        base_q = base_q.filter(Payment.merchant_id == mid)

    all_payments = base_q.all()

    # Build per-day buckets
    day_map: Dict[str, Dict] = {}
    for i in range(days):
        day_label = (datetime.datetime.utcnow() - datetime.timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        day_map[day_label] = {
            "date": day_label,
            "failed_count": 0,
            "failed_value_inr": 0.0,
            "recovered_count": 0,
            "recovered_value_inr": 0.0,
        }

    for p in all_payments:
        day_label = p.created_at.strftime("%Y-%m-%d")
        if day_label not in day_map:
            continue
        if p.status == "FAILED":
            day_map[day_label]["failed_count"] += 1
            day_map[day_label]["failed_value_inr"] += float(p.amount or 0)
        elif p.status == "RECOVERED":
            day_map[day_label]["recovered_count"] += 1
            day_map[day_label]["recovered_value_inr"] += float(p.amount or 0)

    # Round values
    for d in day_map.values():
        d["failed_value_inr"] = round(d["failed_value_inr"], 2)
        d["recovered_value_inr"] = round(d["recovered_value_inr"], 2)

    return {
        "period_days": days,
        "trend": list(day_map.values()),
    }


# ---------------------------------------------------------------------------
# 6. Top At-Risk Customers
# ---------------------------------------------------------------------------
@router.get("/top-risk-customers")
def get_top_risk_customers(
    limit: int = Query(10, ge=1, le=50),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Returns customers with the highest total failed payment value in the window,
    joined with their average risk score for triage prioritisation.
    """
    mid = _merchant_filter(current_user)
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    q = (
        db.query(
            Payment.customer_id,
            Customer.email,
            func.count(Payment.id).label("failed_count"),
            func.sum(Payment.amount).label("total_at_risk"),
            func.avg(RiskAssessment.risk_score).label("avg_risk_score"),
        )
        .join(Customer, Customer.id == Payment.customer_id)
        .outerjoin(RiskAssessment, RiskAssessment.payment_id == Payment.id)
        .filter(Payment.created_at >= since, Payment.status == "FAILED")
    )
    if mid:
        q = q.filter(Payment.merchant_id == mid)

    rows = (
        q.group_by(Payment.customer_id, Customer.email)
        .order_by(func.sum(Payment.amount).desc())
        .limit(limit)
        .all()
    )

    return {
        "period_days": days,
        "top_risk_customers": [
            {
                "customer_id": row.customer_id,
                "email": row.email,
                "failed_payment_count": row.failed_count,
                "total_at_risk_inr": round(float(row.total_at_risk or 0), 2),
                "average_risk_score": round(float(row.avg_risk_score or 0), 4),
            }
            for row in rows
        ],
    }


# ---------------------------------------------------------------------------
# 7. Per-Merchant Leaderboard (admin only)
# ---------------------------------------------------------------------------
@router.get("/merchant-leaderboard")
def get_merchant_leaderboard(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Admin-only: ranks merchants by revenue recovery rate over the period.
    Returns top 20 merchants sorted by recovery rate descending.
    """
    if current_user.role == "merchant":
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Merchant leaderboard is restricted to admin users.",
        )

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    rows = (
        db.query(
            Payment.merchant_id,
            func.count(Payment.id).label("total"),
            func.sum(case((Payment.status == "FAILED", 1), else_=0)).label("failed"),
            func.sum(case((Payment.status == "RECOVERED", 1), else_=0)).label("recovered"),
            func.sum(case((Payment.status == "FAILED", Payment.amount), else_=0)).label("failed_value"),
            func.sum(case((Payment.status == "RECOVERED", Payment.amount), else_=0)).label("recovered_value"),
        )
        .filter(Payment.created_at >= since)
        .group_by(Payment.merchant_id)
        .order_by(func.sum(case((Payment.status == "RECOVERED", Payment.amount), else_=0)).desc())
        .limit(20)
        .all()
    )

    return {
        "period_days": days,
        "leaderboard": [
            {
                "merchant_id": row.merchant_id,
                "total_payments": row.total,
                "failed": int(row.failed or 0),
                "recovered": int(row.recovered or 0),
                "failed_value_inr": round(float(row.failed_value or 0), 2),
                "recovered_value_inr": round(float(row.recovered_value or 0), 2),
                "revenue_recovery_rate_pct": round(
                    (float(row.recovered_value or 0) / float(row.failed_value or 1) * 100), 2
                ),
            }
            for row in rows
        ],
    }
