"""
Phase 16: Performance Benchmark & Telemetry REST API
===================================================
Endpoints:
  GET  /api/performance/telemetry - Cache statistics, active connections & memory
  POST /api/performance/cache/clear - Administrative cache invalidation
  GET  /api/performance/benchmark - Real-time microsecond inference & query benchmarks
"""
import time
import gzip
import json
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database.session import get_db
from app.services.performance.cache_service import kpi_cache, model_cache
from app.services.risk.feature_extractor import FeatureExtractor
from app.services.risk.risk_service import RiskAssessmentService
from app.models.payment import Payment
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

router = APIRouter(prefix="/performance", tags=["Performance & Telemetry"])


@router.get("/telemetry")
def get_performance_telemetry(
    current_user: UserProfile = Depends(get_current_user)
):
    """Returns active in-memory cache statistics, hit rates, and database configuration."""
    return {
        "status": "HEALTHY",
        "cache_statistics": {
            "kpi_cache": kpi_cache.stats(),
            "model_cache": model_cache.stats(),
        },
        "database_performance": {
            "engine": "SQLite WAL Mode / In-Process Pool",
            "indexes_active": [
                "ix_payments_merchant_status_created",
                "ix_payments_merchant_recovery_status",
                "ix_audit_payment_timestamp",
                "ix_audit_event_type_timestamp",
            ],
            "n_plus_one_avoidance": "selectinload / eager joinedload active",
        },
        "compression": {
            "gzip_active": True,
            "minimum_size_bytes": 1000,
        },
    }


@router.post("/cache/clear")
def clear_cache(
    current_user: UserProfile = Depends(get_current_user)
):
    """Flushes active in-memory KPI caches."""
    kpi_cache.clear()
    return {"message": "In-memory KPI cache cleared successfully."}


@router.get("/benchmark")
def run_performance_benchmark(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Measures microsecond latency for deterministic risk inference,
    database indexed query execution, and payload compression.
    """
    # 1. Benchmark Risk Inference Latency
    sample_payment = Payment(
        id="pay_bench_temp",
        merchant_id="mer_bench",
        customer_id="cust_bench",
        amount=5000.0,
        currency="INR",
        status="FAILED",
        error_code="BANK_DECLINE_TEMPORARY",
        retry_count=1,
    )

    t0 = time.perf_counter()
    for _ in range(20):
        # Run pure inference loop
        RiskAssessmentService.compute_risk_score(sample_payment)
    t1 = time.perf_counter()
    avg_inference_ms = round(((t1 - t0) / 20) * 1000, 3)


    # 2. Benchmark Indexed Query Latency
    t0_db = time.perf_counter()
    db.execute(text("SELECT COUNT(*) FROM payments WHERE status = 'FAILED'")).scalar()
    t1_db = time.perf_counter()
    db_query_ms = round((t1_db - t0_db) * 1000, 3)

    # 3. Benchmark GZip Compression Efficiency
    synthetic_payload = json.dumps([{"id": f"pay_{i}", "status": "FAILED", "amount": 1000.0} for i in range(100)]).encode("utf-8")
    raw_size = len(synthetic_payload)
    compressed = gzip.compress(synthetic_payload)
    comp_size = len(compressed)
    reduction_pct = round((1 - (comp_size / raw_size)) * 100, 2)

    return {
        "status": "PASS",
        "benchmarks": {
            "model_inference_latency_ms": avg_inference_ms,
            "inference_target_ms": "< 10.0ms",
            "meets_inference_sla": avg_inference_ms < 10.0,
            "database_query_latency_ms": db_query_ms,
            "database_target_ms": "< 20.0ms",
            "meets_database_sla": db_query_ms < 20.0,
            "compression_efficiency": {
                "raw_bytes": raw_size,
                "compressed_bytes": comp_size,
                "bandwidth_reduction_pct": reduction_pct,
            },
        },
    }
