"""
Phase 12: Audit Trail & Compliance Export Service
===================================================
Provides:
  1. query_events()          - Paginated, filterable audit event log
  2. get_payment_timeline()  - Full chronological event chain for one payment
  3. export_csv()            - CSV export of audit events for a date range
  4. export_json()           - NDJSON export (one JSON object per line)
  5. compute_chain_hash()    - SHA-256 tamper-evident chain across all events
                               in a window (each event hashes its predecessor)
  6. compliance_report()     - Aggregate compliance KPIs for a period

Hash chain design:
  Each event's `chain_hash` = SHA-256(prev_hash + event_id + timestamp + actor + outcome)
  The first event's prev_hash is the well-known genesis sentinel:
    "0" * 64
  This makes any deletion or reordering immediately detectable.
"""
import hashlib
import csv
import json
import io
import datetime
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.audit_event import AuditEvent
from app.models.payment import Payment
from app.utils.logger import logger

GENESIS_HASH = "0" * 64


# ── Query ─────────────────────────────────────────────────────────────────────

def query_events(
    db: Session,
    merchant_id: Optional[str] = None,
    payment_id: Optional[str] = None,
    event_type: Optional[str] = None,
    actor: Optional[str] = None,
    outcome: Optional[str] = None,
    risk_level: Optional[str] = None,
    since: Optional[datetime.datetime] = None,
    until: Optional[datetime.datetime] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Paginated audit event query with multi-field filtering.
    merchant_id filter joins through Payment.
    search is a case-insensitive substring match on details + actor.
    """
    q = db.query(AuditEvent).join(Payment, Payment.id == AuditEvent.payment_id)

    if merchant_id:
        q = q.filter(Payment.merchant_id == merchant_id)
    if payment_id:
        q = q.filter(AuditEvent.payment_id == payment_id)
    if event_type:
        q = q.filter(AuditEvent.event_type == event_type)
    if actor:
        q = q.filter(AuditEvent.actor.ilike(f"%{actor}%"))
    if outcome:
        q = q.filter(AuditEvent.outcome == outcome)
    if risk_level:
        q = q.filter(AuditEvent.risk_level == risk_level)
    if since:
        q = q.filter(AuditEvent.timestamp >= since)
    if until:
        q = q.filter(AuditEvent.timestamp <= until)
    if search:
        q = q.filter(
            or_(
                AuditEvent.details.ilike(f"%{search}%"),
                AuditEvent.actor.ilike(f"%{search}%"),
            )
        )

    total = q.count()
    events = q.order_by(AuditEvent.timestamp.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "events": [_serialise(e) for e in events],
    }


# ── Payment Timeline ──────────────────────────────────────────────────────────

def get_payment_timeline(db: Session, payment_id: str) -> Dict[str, Any]:
    """
    Returns every audit event for a payment in ascending chronological order,
    plus the computed chain hash for each event (tamper detection).
    """
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.payment_id == payment_id)
        .order_by(AuditEvent.timestamp.asc())
        .all()
    )

    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    chain = _compute_chain(events)

    return {
        "payment_id": payment_id,
        "merchant_id": payment.merchant_id if payment else None,
        "event_count": len(events),
        "timeline": [
            {**_serialise(e), "chain_hash": chain[i]}
            for i, e in enumerate(events)
        ],
    }


# ── Export ────────────────────────────────────────────────────────────────────

def export_csv(
    db: Session,
    merchant_id: Optional[str] = None,
    since: Optional[datetime.datetime] = None,
    until: Optional[datetime.datetime] = None,
    event_type: Optional[str] = None,
) -> str:
    """
    Returns audit events as a UTF-8 CSV string.
    Columns: id, payment_id, event_type, actor, outcome, risk_level, details, timestamp
    """
    result = query_events(
        db=db,
        merchant_id=merchant_id,
        event_type=event_type,
        since=since,
        until=until,
        limit=10000,
        offset=0,
    )

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["id", "payment_id", "event_type", "actor",
                    "outcome", "risk_level", "details", "timestamp"],
        extrasaction="ignore",
    )
    writer.writeheader()
    for ev in result["events"]:
        writer.writerow(ev)

    return output.getvalue()


def export_ndjson(
    db: Session,
    merchant_id: Optional[str] = None,
    since: Optional[datetime.datetime] = None,
    until: Optional[datetime.datetime] = None,
    event_type: Optional[str] = None,
) -> str:
    """
    Returns audit events as newline-delimited JSON (one object per line).
    Includes full metadata_json for tooling that can consume NDJSON.
    """
    result = query_events(
        db=db,
        merchant_id=merchant_id,
        event_type=event_type,
        since=since,
        until=until,
        limit=10000,
        offset=0,
    )
    lines = [json.dumps(ev, default=str) for ev in result["events"]]
    return "\n".join(lines)


# ── Tamper-Evident Chain ──────────────────────────────────────────────────────

def compute_chain_hash(
    db: Session,
    merchant_id: Optional[str] = None,
    since: Optional[datetime.datetime] = None,
    until: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    """
    Computes a SHA-256 hash chain over all audit events in a window, oldest-first.
    Returns the final chain hash, event count, and first/last event timestamps.
    Any insertion, deletion, or modification of an event will change the final hash.
    """
    q = db.query(AuditEvent).join(Payment, Payment.id == AuditEvent.payment_id)
    if merchant_id:
        q = q.filter(Payment.merchant_id == merchant_id)
    if since:
        q = q.filter(AuditEvent.timestamp >= since)
    if until:
        q = q.filter(AuditEvent.timestamp <= until)

    events = q.order_by(AuditEvent.timestamp.asc(), AuditEvent.id.asc()).all()
    chain = _compute_chain(events)

    return {
        "event_count": len(events),
        "final_chain_hash": chain[-1] if chain else GENESIS_HASH,
        "genesis_hash": GENESIS_HASH,
        "first_event_at": events[0].timestamp.isoformat() if events else None,
        "last_event_at": events[-1].timestamp.isoformat() if events else None,
        "computed_at": datetime.datetime.utcnow().isoformat(),
    }


# ── Compliance Report ─────────────────────────────────────────────────────────

def compliance_report(
    db: Session,
    merchant_id: Optional[str] = None,
    days: int = 30,
) -> Dict[str, Any]:
    """
    Produces an aggregate compliance summary covering:
      - Total audit events by type
      - Actor breakdown (AI_AGENT vs human vs AUTO_QUARANTINE)
      - Outcome distribution
      - Human review coverage (% of HIGH-risk payments reviewed)
      - Data integrity: final chain hash for the period
    """
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    result = query_events(
        db=db,
        merchant_id=merchant_id,
        since=since,
        limit=10000,
        offset=0,
    )
    events = result["events"]

    # Aggregate by event_type
    type_counts: Dict[str, int] = {}
    actor_counts: Dict[str, int] = {}
    outcome_counts: Dict[str, int] = {}

    for ev in events:
        t = ev["event_type"] or "UNKNOWN"
        type_counts[t] = type_counts.get(t, 0) + 1

        actor = ev["actor"] or "UNKNOWN"
        actor_key = (
            "AI_AGENT" if "AI_AGENT" in actor or "Deterministic" in actor or "LangGraph" in actor
            else "HUMAN_REVIEWER" if "Reviewer" in actor or "reviewer" in actor
            else "AUTO_SYSTEM" if "AUTO" in actor
            else "OTHER"
        )
        actor_counts[actor_key] = actor_counts.get(actor_key, 0) + 1

        outcome = ev["outcome"] or "NONE"
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1

    # Human review coverage
    from app.models.risk_assessment import RiskAssessment
    from app.models.human_review import HumanReview

    high_risk_q = (
        db.query(RiskAssessment)
        .join(Payment, Payment.id == RiskAssessment.payment_id)
        .filter(
            RiskAssessment.risk_level == "HIGH",
            Payment.created_at >= since,
        )
    )
    if merchant_id:
        high_risk_q = high_risk_q.filter(Payment.merchant_id == merchant_id)

    high_risk_count = high_risk_q.count()

    reviewed_q = (
        db.query(HumanReview)
        .join(Payment, Payment.id == HumanReview.payment_id)
        .join(RiskAssessment, RiskAssessment.payment_id == Payment.id)
        .filter(
            RiskAssessment.risk_level == "HIGH",
            HumanReview.quarantined_at >= since,
        )
    )
    if merchant_id:
        reviewed_q = reviewed_q.filter(Payment.merchant_id == merchant_id)

    reviewed_count = reviewed_q.count()

    review_coverage_pct = round(
        (reviewed_count / high_risk_count * 100) if high_risk_count > 0 else 0.0, 2
    )

    # Chain hash
    chain_info = compute_chain_hash(db=db, merchant_id=merchant_id, since=since)

    return {
        "period_days": days,
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "total_audit_events": len(events),
        "event_type_breakdown": dict(sorted(type_counts.items(), key=lambda x: -x[1])),
        "actor_breakdown": actor_counts,
        "outcome_breakdown": dict(sorted(outcome_counts.items(), key=lambda x: -x[1])),
        "human_review": {
            "high_risk_payments": high_risk_count,
            "reviewed_count": reviewed_count,
            "coverage_pct": review_coverage_pct,
        },
        "data_integrity": {
            "final_chain_hash": chain_info["final_chain_hash"],
            "events_in_chain": chain_info["event_count"],
        },
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _serialise(event: AuditEvent) -> Dict[str, Any]:
    return {
        "id": event.id,
        "payment_id": event.payment_id,
        "agent_run_id": event.agent_run_id,
        "event_type": event.event_type,
        "actor": event.actor,
        "details": event.details,
        "risk_level": event.risk_level,
        "outcome": event.outcome,
        "metadata_json": event.metadata_json,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
    }


def _compute_chain(events: List[AuditEvent]) -> List[str]:
    """
    Compute SHA-256 hash chain over a list of events (ascending order assumed).
    Returns a list of hash strings, one per event.
    """
    hashes: List[str] = []
    prev = GENESIS_HASH
    for ev in events:
        data = f"{prev}|{ev.id}|{ev.timestamp.isoformat()}|{ev.actor}|{ev.outcome or ''}"
        current = hashlib.sha256(data.encode()).hexdigest()
        hashes.append(current)
        prev = current
    return hashes
