"""
Phase 13: Batch Recovery Engine & Metrics Service
=================================================
Provides end-to-end batch processing for failed payment triage:
  1. run_batch_recovery()          - Filter, prioritize, triage, and safely execute recovery on N payments
  2. simulate_demo_batch()         - Generate certified synthetic demo batch (100 payments, 48% recovery rate)
  3. get_batch_run_detail()        - Full breakdown of a single batch run with itemized outcomes
  4. list_batch_runs()             - Paginated history of batch runs (merchant-isolated)
  5. get_aggregate_batch_metrics() - Aggregate recovery rate, total revenue saved, and escalation rate KPIs
"""
import uuid
import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.models.payment import Payment
from app.models.risk_assessment import RiskAssessment
from app.models.audit_event import AuditEvent
from app.models.batch_run import BatchRun, BatchRunItem
from app.services.risk.risk_service import RiskAssessmentService
from app.services.recovery.recovery_decision_service import RecoveryDecisionService
from app.services.recovery.execution_service import RecoveryExecutionService
from app.services.recovery.human_review_service import HumanReviewService
from app.services.webhooks.webhook_dispatcher import WebhookDispatcherService
from app.utils.logger import logger


class BatchRecoveryService:
    """
    Orchestrates batch recovery workflows over pools of failed payments
    with strict idempotency, safety ceilings, and multi-tenant scoping.
    """

    MAX_BATCH_LIMIT = 200

    @classmethod
    def run_batch_recovery(
        cls,
        db: Session,
        merchant_id: Optional[str] = None,
        payment_ids: Optional[List[str]] = None,
        max_batch_size: int = 50,
        dry_run: bool = False,
        triggered_by: str = "SYSTEM",
        prioritization: str = "AMOUNT_DESC",
    ) -> BatchRun:
        """
        Executes a batch recovery run over candidate payments.
        Flow:
          1. Select & order candidate payments according to prioritization.
          2. Evaluate risk deterministically.
          3. Route HIGH-risk / max-retry candidates to HumanReview quarantine.
          4. Execute safe recovery actions for LOW/MEDIUM risk candidates.
          5. Compute batch financial and operational metrics.
          6. Record immutable AuditEvent and dispatch outbound webhook.
        """
        limit = min(max(1, max_batch_size), cls.MAX_BATCH_LIMIT)

        # ── 1. Query Candidate Payments ──────────────────────────────────────
        q = db.query(Payment)

        if payment_ids:
            q = q.filter(Payment.id.in_(payment_ids))
            if merchant_id:
                q = q.filter(Payment.merchant_id == merchant_id)
        else:
            # Fetch active failed / held payments not yet recovered
            q = q.filter(
                Payment.status.in_(["FAILED", "HELD", "SCHEDULED"]),
                Payment.recovery_status != "RECOVERED",
            )
            if merchant_id:
                q = q.filter(Payment.merchant_id == merchant_id)

        # Apply prioritization
        if prioritization == "AMOUNT_DESC":
            q = q.order_by(desc(Payment.amount))
        elif prioritization == "NEWEST_FIRST":
            q = q.order_by(desc(Payment.created_at))
        else:
            q = q.order_by(Payment.created_at.asc())

        payments: List[Payment] = q.limit(limit).all()

        # ── 2. Initialize BatchRun Record ─────────────────────────────────────
        batch_id = f"batch_{uuid.uuid4().hex[:14]}"
        batch_run = BatchRun(
            id=batch_id,
            merchant_id=merchant_id,
            triggered_by=triggered_by,
            status="RUNNING",
            total_payments=len(payments),
            processed_count=0,
            recovered_count=0,
            quarantined_count=0,
            failed_count=0,
            skipped_count=0,
            revenue_at_risk=sum(p.amount for p in payments),
            revenue_recovered=0.0,
            recovery_rate=0.0,
            avg_attempts=0.0,
            escalation_rate=0.0,
            is_demo=False,
            parameters_json={
                "max_batch_size": limit,
                "dry_run": dry_run,
                "prioritization": prioritization,
                "specified_ids_count": len(payment_ids) if payment_ids else None,
            },
            started_at=datetime.datetime.utcnow(),
        )
        db.add(batch_run)
        db.commit()

        # ── 3. Process Each Payment ──────────────────────────────────────────
        total_attempts = 0
        revenue_recovered = 0.0
        recovered_count = 0
        quarantined_count = 0
        failed_count = 0
        skipped_count = 0
        processed_count = 0

        for payment in payments:
            initial_status = payment.status
            item_id = f"bi_{uuid.uuid4().hex[:12]}"

            # Check terminal / already recovered
            if payment.status == "RECOVERED" or payment.recovery_status == "RECOVERED":
                skipped_count += 1
                item = BatchRunItem(
                    id=item_id,
                    batch_run_id=batch_id,
                    payment_id=payment.id,
                    initial_status=initial_status,
                    final_status=payment.status,
                    amount=payment.amount,
                    outcome="SKIPPED",
                    details="Payment is already marked as recovered.",
                    processed_at=datetime.datetime.utcnow(),
                )
                db.add(item)
                continue

            # Fetch or compute risk assessment
            risk = db.query(RiskAssessment).filter(RiskAssessment.payment_id == payment.id).first()
            if not risk:
                try:
                    risk = RiskAssessmentService.evaluate_payment_risk(db, payment)
                except Exception as e:
                    logger.warning(f"Batch inference fallback on {payment.id}: {e}")
                    risk = None

            risk_score = float(risk.risk_score) if risk and risk.risk_score is not None else 0.50
            risk_level = risk.risk_level if risk and risk.risk_level else "MEDIUM"

            # Check hard retry cap (3 attempts ceiling)
            if (payment.retry_count or 0) >= RecoveryExecutionService.MAX_RETRY_LIMIT:
                if not dry_run and payment.status != "IN_REVIEW":
                    try:
                        HumanReviewService.quarantine_payment(
                            db, payment.id,
                            f"Batch triage: Max retries ({RecoveryExecutionService.MAX_RETRY_LIMIT}) reached.",
                            actor=f"BatchEngine:{triggered_by}"
                        )
                    except Exception as q_err:
                        logger.warning(f"Quarantine skipped for {payment.id}: {q_err}")

                quarantined_count += 1
                processed_count += 1
                item = BatchRunItem(
                    id=item_id,
                    batch_run_id=batch_id,
                    payment_id=payment.id,
                    initial_status=initial_status,
                    final_status="IN_REVIEW" if not dry_run else initial_status,
                    risk_score=risk_score,
                    risk_level=risk_level,
                    amount=payment.amount,
                    recovery_action="ESCALATE",
                    outcome="QUARANTINED",
                    details=f"Safety Guardrail: Max retry attempts ({RecoveryExecutionService.MAX_RETRY_LIMIT}) exhausted.",
                    processed_at=datetime.datetime.utcnow(),
                )
                db.add(item)
                continue

            # Check HIGH risk: route to Human Review
            if risk_level == "HIGH" or risk_score >= 0.70:
                if not dry_run and payment.status != "IN_REVIEW":
                    try:
                        HumanReviewService.quarantine_payment(
                            db, payment.id,
                            f"Batch triage: Flagged HIGH risk (score {risk_score:.2f}).",
                            actor=f"BatchEngine:{triggered_by}"
                        )
                    except Exception as q_err:
                        logger.warning(f"Quarantine skipped for {payment.id}: {q_err}")

                quarantined_count += 1
                processed_count += 1
                item = BatchRunItem(
                    id=item_id,
                    batch_run_id=batch_id,
                    payment_id=payment.id,
                    initial_status=initial_status,
                    final_status="IN_REVIEW" if not dry_run else initial_status,
                    risk_score=risk_score,
                    risk_level=risk_level,
                    amount=payment.amount,
                    recovery_action="ESCALATE",
                    outcome="QUARANTINED",
                    details=f"High Risk Guardrail: Routed to human review queue (Risk score {risk_score:.2f}).",
                    processed_at=datetime.datetime.utcnow(),
                )
                db.add(item)
                continue

            # Candidate is LOW or MEDIUM risk -> Safe for automated recovery
            if dry_run:
                # Dry run: formulate decision and predict outcome without state changes
                decision = RecoveryDecisionService.decide_recovery_action(db, payment)
                predicted_recoverable = (decision.action_type in ("RETRY", "CREATE_PAYMENT_LINK") and risk_level == "LOW")
                
                if predicted_recoverable:
                    recovered_count += 1
                    revenue_recovered += payment.amount
                    outcome = "PREDICTED_RECOVERABLE"
                    details = f"Dry-run: Predicted successful recovery via {decision.action_type}."
                else:
                    outcome = "DRY_RUN_EVALUATED"
                    details = f"Dry-run: Evaluated action {decision.action_type} (Risk: {risk_level})."

                processed_count += 1
                item = BatchRunItem(
                    id=item_id,
                    batch_run_id=batch_id,
                    payment_id=payment.id,
                    initial_status=initial_status,
                    final_status=initial_status,
                    risk_score=risk_score,
                    risk_level=risk_level,
                    amount=payment.amount,
                    recovery_action=decision.action_type,
                    outcome=outcome,
                    details=details,
                    processed_at=datetime.datetime.utcnow(),
                )
                db.add(item)
            else:
                # Live execution through guarded recovery execution engine
                decision = RecoveryDecisionService.decide_recovery_action(db, payment)
                exec_res = RecoveryExecutionService.execute_recovery_action(db, payment, decision)
                total_attempts += (payment.retry_count or 1)
                processed_count += 1

                if exec_res.success:
                    recovered_count += 1
                    revenue_recovered += payment.amount
                    outcome = "RECOVERED"
                    details = f"Recovered successfully via {decision.action_type}."
                    payment.status = "RECOVERED"
                    payment.recovery_status = "RECOVERED"
                elif exec_res.status in ("ESCALATED", "BLOCKED"):
                    quarantined_count += 1
                    outcome = "QUARANTINED"
                    details = exec_res.details
                else:
                    failed_count += 1
                    outcome = "FAILED"
                    details = exec_res.details

                item = BatchRunItem(
                    id=item_id,
                    batch_run_id=batch_id,
                    payment_id=payment.id,
                    initial_status=initial_status,
                    final_status=payment.status,
                    risk_score=risk_score,
                    risk_level=risk_level,
                    amount=payment.amount,
                    recovery_action=decision.action_type,
                    outcome=outcome,
                    details=details,
                    processed_at=datetime.datetime.utcnow(),
                )
                db.add(item)

        # ── 4. Finalize Batch Metrics ─────────────────────────────────────────
        rev_at_risk = batch_run.revenue_at_risk
        recovery_rate = round((revenue_recovered / rev_at_risk * 100), 2) if rev_at_risk > 0 else 0.0
        escalation_rate = round((quarantined_count / len(payments) * 100), 2) if payments else 0.0
        avg_attempts = round((total_attempts / processed_count), 2) if processed_count > 0 else 0.0

        batch_run.processed_count = processed_count
        batch_run.recovered_count = recovered_count
        batch_run.quarantined_count = quarantined_count
        batch_run.failed_count = failed_count
        batch_run.skipped_count = skipped_count
        batch_run.revenue_recovered = revenue_recovered
        batch_run.recovery_rate = recovery_rate
        batch_run.avg_attempts = avg_attempts
        batch_run.escalation_rate = escalation_rate
        batch_run.completed_at = datetime.datetime.utcnow()

        if len(payments) == 0:
            batch_run.status = "COMPLETED"
        elif recovered_count > 0 and failed_count > 0:
            batch_run.status = "PARTIAL"
        elif failed_count > 0 and recovered_count == 0 and quarantined_count == 0:
            batch_run.status = "FAILED"
        else:
            batch_run.status = "COMPLETED"

        batch_run.metrics_json = {
            "recovery_rate_pct": recovery_rate,
            "escalation_rate_pct": escalation_rate,
            "avg_retry_attempts": avg_attempts,
            "revenue_at_risk": rev_at_risk,
            "revenue_recovered": revenue_recovered,
            "net_revenue_yield": revenue_recovered,
        }

        db.commit()
        db.refresh(batch_run)

        # ── 5. Record Audit Event ─────────────────────────────────────────────
        try:
            ae = AuditEvent(
                id=f"ae_{uuid.uuid4().hex[:16]}",
                payment_id=payments[0].id if payments else "system_batch",
                agent_run_id=batch_run.id,
                event_type="BATCH_RECOVERY_COMPLETED",
                actor=f"BatchEngine:{triggered_by}",
                details=(
                    f"Batch recovery run {batch_run.id} finished. Processed: {processed_count}, "
                    f"Recovered: {recovered_count}, Quarantined: {quarantined_count}, "
                    f"Recovered Revenue: INR {revenue_recovered:,.2f} ({recovery_rate:.1f}% rate)."
                ),
                risk_level="LOW" if recovery_rate >= 50 else "MEDIUM",
                outcome=batch_run.status,
                metadata_json=batch_run.metrics_json,
                timestamp=datetime.datetime.utcnow(),
            )
            db.add(ae)
            db.commit()
        except Exception as ae_err:
            logger.warning(f"Batch audit event logging skipped: {ae_err}")

        # ── 6. Outbound Webhook Dispatch ──────────────────────────────────────
        if merchant_id and not dry_run:
            try:
                WebhookDispatcherService.dispatch_event(
                    db=db,
                    merchant_id=merchant_id,
                    event_type="recovery.batch_completed",
                    payment_id=None,
                    data={
                        "batch_id": batch_run.id,
                        "status": batch_run.status,
                        "processed_count": processed_count,
                        "recovered_count": recovered_count,
                        "quarantined_count": quarantined_count,
                        "revenue_at_risk": rev_at_risk,
                        "revenue_recovered": revenue_recovered,
                        "recovery_rate": recovery_rate,
                    }
                )
            except Exception as wh_err:
                logger.warning(f"Outbound webhook dispatch skipped: {wh_err}")

        logger.info(
            f"Batch {batch_run.id} completed: {recovered_count}/{processed_count} recovered "
            f"({recovery_rate}% yield, INR {revenue_recovered:,.2f})"
        )
        return batch_run

    @classmethod
    def simulate_demo_batch(
        cls,
        db: Session,
        merchant_id: Optional[str] = None,
        total_payments: int = 100,
        target_revenue_at_risk: float = 250000.0,
        target_revenue_recovered: float = 120000.0,
        triggered_by: str = "DEMO_SIMULATOR",
    ) -> BatchRun:
        """
        Generates a certified synthetic demo batch matching the specification:
          - 100 failed payments
          - INR 2,50,000 Revenue at Risk
          - INR 1,20,000 Recovered (48% Recovery Rate)
          - 22 Quarantined to Human Review (High Risk)
          - 30 Failed / Max retries exhausted
        All items and metrics are persisted with is_demo=True.
        """
        batch_id = f"batch_demo_{uuid.uuid4().hex[:10]}"
        recovery_rate = round((target_revenue_recovered / target_revenue_at_risk * 100), 2)

        batch_run = BatchRun(
            id=batch_id,
            merchant_id=merchant_id,
            triggered_by=triggered_by,
            status="COMPLETED",
            total_payments=total_payments,
            processed_count=total_payments,
            recovered_count=48,
            quarantined_count=22,
            failed_count=30,
            skipped_count=0,
            revenue_at_risk=target_revenue_at_risk,
            revenue_recovered=target_revenue_recovered,
            recovery_rate=recovery_rate,
            avg_attempts=1.42,
            escalation_rate=22.0,
            is_demo=True,
            parameters_json={
                "is_synthetic": True,
                "demo_scenario": "Phase 13 Benchmark Demo (100 Payments, 48% Recovery)",
            },
            metrics_json={
                "recovery_rate_pct": recovery_rate,
                "escalation_rate_pct": 22.0,
                "avg_retry_attempts": 1.42,
                "revenue_at_risk": target_revenue_at_risk,
                "revenue_recovered": target_revenue_recovered,
                "net_revenue_yield": target_revenue_recovered,
                "risk_detection_precision": 0.94,
                "false_positive_rate": 0.04,
            },
            started_at=datetime.datetime.utcnow() - datetime.timedelta(minutes=3),
            completed_at=datetime.datetime.utcnow(),
        )
        db.add(batch_run)
        db.commit()

        # Seed realistic demo item breakdown
        # 1. 48 Recovered items
        avg_recovered_amt = round(target_revenue_recovered / 48, 2)
        for i in range(48):
            item = BatchRunItem(
                id=f"bi_demo_rec_{i+1:03d}",
                batch_run_id=batch_id,
                payment_id=f"pay_demo_rec_{i+1:03d}",
                initial_status="FAILED",
                final_status="RECOVERED",
                risk_score=round(0.10 + (i % 20) * 0.01, 2),
                risk_level="LOW",
                amount=avg_recovered_amt,
                recovery_action="RETRY" if i % 2 == 0 else "CREATE_PAYMENT_LINK",
                outcome="RECOVERED",
                details="[SYNTHETIC DEMO] Payment successfully recovered via smart retry.",
                processed_at=datetime.datetime.utcnow() - datetime.timedelta(seconds=180 - i),
            )
            db.add(item)

        # 2. 22 Quarantined items (High Risk)
        for i in range(22):
            item = BatchRunItem(
                id=f"bi_demo_quar_{i+1:03d}",
                batch_run_id=batch_id,
                payment_id=f"pay_demo_quar_{i+1:03d}",
                initial_status="FAILED",
                final_status="IN_REVIEW",
                risk_score=round(0.72 + (i % 25) * 0.01, 2),
                risk_level="HIGH",
                amount=round((target_revenue_at_risk - target_revenue_recovered) * 0.50 / 22, 2),
                recovery_action="ESCALATE",
                outcome="QUARANTINED",
                details="[SYNTHETIC DEMO] Auto-quarantined to Human Review due to high risk signals.",
                processed_at=datetime.datetime.utcnow() - datetime.timedelta(seconds=120 - i),
            )
            db.add(item)

        # 3. 30 Failed items
        for i in range(30):
            item = BatchRunItem(
                id=f"bi_demo_fail_{i+1:03d}",
                batch_run_id=batch_id,
                payment_id=f"pay_demo_fail_{i+1:03d}",
                initial_status="FAILED",
                final_status="FAILED",
                risk_score=round(0.40 + (i % 20) * 0.01, 2),
                risk_level="MEDIUM",
                amount=round((target_revenue_at_risk - target_revenue_recovered) * 0.50 / 30, 2),
                recovery_action="RETRY",
                outcome="FAILED",
                details="[SYNTHETIC DEMO] Card issuer declined with permanent account closure.",
                processed_at=datetime.datetime.utcnow() - datetime.timedelta(seconds=60 - i),
            )
            db.add(item)

        db.commit()
        db.refresh(batch_run)
        return batch_run

    @classmethod
    def get_batch_run_detail(
        cls,
        db: Session,
        batch_run_id: str,
        merchant_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Returns single batch run with its items, respecting merchant isolation."""
        q = db.query(BatchRun).filter(BatchRun.id == batch_run_id)
        if merchant_id:
            q = q.filter(BatchRun.merchant_id == merchant_id)
        batch = q.first()
        if not batch:
            return None

        items = (
            db.query(BatchRunItem)
            .filter(BatchRunItem.batch_run_id == batch.id)
            .order_by(BatchRunItem.processed_at.asc())
            .all()
        )

        return {
            "id": batch.id,
            "merchant_id": batch.merchant_id,
            "triggered_by": batch.triggered_by,
            "status": batch.status,
            "total_payments": batch.total_payments,
            "processed_count": batch.processed_count,
            "recovered_count": batch.recovered_count,
            "quarantined_count": batch.quarantined_count,
            "failed_count": batch.failed_count,
            "skipped_count": batch.skipped_count,
            "revenue_at_risk": batch.revenue_at_risk,
            "revenue_recovered": batch.revenue_recovered,
            "recovery_rate": batch.recovery_rate,
            "avg_attempts": batch.avg_attempts,
            "escalation_rate": batch.escalation_rate,
            "is_demo": batch.is_demo,
            "parameters": batch.parameters_json,
            "metrics": batch.metrics_json,
            "started_at": batch.started_at.isoformat() if batch.started_at else None,
            "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
            "items": [
                {
                    "id": item.id,
                    "payment_id": item.payment_id,
                    "initial_status": item.initial_status,
                    "final_status": item.final_status,
                    "risk_score": item.risk_score,
                    "risk_level": item.risk_level,
                    "amount": item.amount,
                    "recovery_action": item.recovery_action,
                    "outcome": item.outcome,
                    "details": item.details,
                    "processed_at": item.processed_at.isoformat() if item.processed_at else None,
                }
                for item in items
            ],
        }

    @classmethod
    def list_batch_runs(
        cls,
        db: Session,
        merchant_id: Optional[str] = None,
        include_demo: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Returns paginated batch runs."""
        q = db.query(BatchRun)
        if merchant_id:
            q = q.filter(BatchRun.merchant_id == merchant_id)
        if not include_demo:
            q = q.filter(BatchRun.is_demo == False)

        total = q.count()
        runs = q.order_by(desc(BatchRun.started_at)).offset(offset).limit(limit).all()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "runs": [
                {
                    "id": r.id,
                    "merchant_id": r.merchant_id,
                    "triggered_by": r.triggered_by,
                    "status": r.status,
                    "total_payments": r.total_payments,
                    "processed_count": r.processed_count,
                    "recovered_count": r.recovered_count,
                    "quarantined_count": r.quarantined_count,
                    "failed_count": r.failed_count,
                    "skipped_count": r.skipped_count,
                    "revenue_at_risk": r.revenue_at_risk,
                    "revenue_recovered": r.revenue_recovered,
                    "recovery_rate": r.recovery_rate,
                    "is_demo": r.is_demo,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                }
                for r in runs
            ],
        }

    @classmethod
    def get_aggregate_batch_metrics(
        cls,
        db: Session,
        merchant_id: Optional[str] = None,
        days: int = 30,
        include_demo: bool = True,
    ) -> Dict[str, Any]:
        """Computes aggregate batch performance metrics across runs."""
        since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        q = db.query(BatchRun).filter(BatchRun.started_at >= since)
        if merchant_id:
            q = q.filter(BatchRun.merchant_id == merchant_id)
        if not include_demo:
            q = q.filter(BatchRun.is_demo == False)

        runs = q.all()

        total_runs = len(runs)
        total_payments = sum(r.total_payments for r in runs)
        total_processed = sum(r.processed_count for r in runs)
        total_recovered = sum(r.recovered_count for r in runs)
        total_quarantined = sum(r.quarantined_count for r in runs)
        total_failed = sum(r.failed_count for r in runs)
        revenue_at_risk = sum(r.revenue_at_risk for r in runs)
        revenue_recovered = sum(r.revenue_recovered for r in runs)

        overall_recovery_rate = (
            round((revenue_recovered / revenue_at_risk * 100), 2)
            if revenue_at_risk > 0 else 0.0
        )
        overall_escalation_rate = (
            round((total_quarantined / total_processed * 100), 2)
            if total_processed > 0 else 0.0
        )

        return {
            "period_days": days,
            "total_batch_runs": total_runs,
            "total_payments_triaged": total_processed,
            "total_payments_recovered": total_recovered,
            "total_payments_quarantined": total_quarantined,
            "total_payments_failed": total_failed,
            "financial_summary": {
                "currency": "INR",
                "total_revenue_at_risk": revenue_at_risk,
                "total_revenue_recovered": revenue_recovered,
                "recovery_rate_pct": overall_recovery_rate,
            },
            "operational_summary": {
                "escalation_rate_pct": overall_escalation_rate,
                "avg_recovery_rate_per_batch": round(
                    sum(r.recovery_rate for r in runs) / total_runs, 2
                ) if total_runs > 0 else 0.0,
            },
            "generated_at": datetime.datetime.utcnow().isoformat(),
        }
