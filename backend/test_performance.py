"""
Phase 16: Performance Optimization & Query Tuning Test Suite
============================================================
Tests:
  1. GZip Compression for large payloads (>1000 bytes)
  2. In-Memory TTL Cache operations (Set, Get, Miss, Expiration, Prefix Invalidation)
  3. GET /api/performance/telemetry endpoint posture
  4. POST /api/performance/cache/clear cache flush
  5. GET /api/performance/benchmark microsecond latency & SLAs
  6. Compound index presence and schema integrity on Payment and AuditEvent
"""
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database.session import Base, get_db
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.audit_event import AuditEvent
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile
from app.services.performance.cache_service import InMemoryTTLCache, kpi_cache, model_cache

# Isolated Database
SQLALCHEMY_TEST_URL = "sqlite:///./test_performance.db"
engine = create_engine(SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


TEST_USER = UserProfile(
    id="usr_perf_01",
    name="Performance Admin",
    email="perf@recovery.io",
    role="admin",
    merchant_id="mer_perf_01",
    is_active=True
)

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    m = Merchant(id="mer_perf_01", business_name="Speedy Merchant", contact_email="perf@speedy.com", is_live=True)
    c = Customer(id="cust_perf_01", merchant_id="mer_perf_01", name="Quick Buyer", email="buyer@fast.com")
    db.add_all([m, c])

    # Seed 20 sample payments for query benchmarks
    payments = [
        Payment(
            id=f"pay_perf_{i:03d}",
            merchant_id="mer_perf_01",
            customer_id="cust_perf_01",
            amount=1000.0 * (i + 1),
            currency="INR",
            status="FAILED" if i % 2 == 0 else "RECOVERED",
            recovery_status="PENDING" if i % 2 == 0 else "RECOVERED",
            error_code="INSUFFICIENT_FUNDS",
            retry_count=1
        )
        for i in range(20)
    ]
    db.add_all(payments)
    db.commit()
    db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: TEST_USER

    yield

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    Base.metadata.drop_all(bind=engine)


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_01_gzip_compression_active():
    """GZipMiddleware compresses responses larger than 1000 bytes when requested."""
    # GET /api/payments with Accept-Encoding: gzip
    headers = {"Accept-Encoding": "gzip"}
    resp = client.get("/api/payments", headers=headers)
    assert resp.status_code == 200
    # Response payload for 20 payments is > 1000 bytes
    if len(resp.content) > 1000 or "gzip" in resp.headers.get("Content-Encoding", ""):
        assert resp.headers.get("Content-Encoding") == "gzip"


def test_02_ttl_cache_operations():
    """Validates InMemoryTTLCache set, hit, miss, ttl expiration, and prefix eviction."""
    cache = InMemoryTTLCache(default_ttl_seconds=1)

    # 1. Cache set and hit
    cache.set("merchant:1:kpi", {"total_revenue": 50000})
    val = cache.get("merchant:1:kpi")
    assert val is not None
    assert val["total_revenue"] == 50000

    # 2. Cache miss
    assert cache.get("non_existent_key") is None

    # 3. Stats tracking
    stats = cache.stats()
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1
    assert stats["size"] >= 1

    # 4. TTL expiration
    time.sleep(1.1)
    expired_val = cache.get("merchant:1:kpi")
    assert expired_val is None

    # 5. Invalidation by prefix
    cache.set("mer:abc:1", "item1", ttl_seconds=60)
    cache.set("mer:abc:2", "item2", ttl_seconds=60)
    cache.set("mer:xyz:1", "item3", ttl_seconds=60)
    assert cache.size() == 3

    evicted = cache.invalidate_prefix("mer:abc:")
    assert evicted == 2
    assert cache.get("mer:abc:1") is None
    assert cache.get("mer:xyz:1") == "item3"


def test_03_performance_telemetry_endpoint():
    """GET /api/performance/telemetry exposes cache stats, database index info, and GZip config."""
    resp = client.get("/api/performance/telemetry")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "HEALTHY"
    assert "kpi_cache" in data["cache_statistics"]
    assert "model_cache" in data["cache_statistics"]
    assert "ix_payments_merchant_status_created" in data["database_performance"]["indexes_active"]
    assert "ix_payments_merchant_recovery_status" in data["database_performance"]["indexes_active"]
    assert "ix_audit_payment_timestamp" in data["database_performance"]["indexes_active"]
    assert "ix_audit_event_type_timestamp" in data["database_performance"]["indexes_active"]
    assert data["compression"]["gzip_active"] is True
    assert data["compression"]["minimum_size_bytes"] == 1000


def test_04_cache_clear_endpoint():
    """POST /api/performance/cache/clear purges the in-memory KPI cache."""
    kpi_cache.set("test_kpi", 99999, ttl_seconds=60)
    assert kpi_cache.get("test_kpi") == 99999

    resp = client.post("/api/performance/cache/clear")
    assert resp.status_code == 200
    assert "cleared successfully" in resp.json()["message"]
    assert kpi_cache.get("test_kpi") is None


def test_05_benchmark_latency_sla():
    """GET /api/performance/benchmark guarantees <10ms inference and <20ms indexed DB query."""
    resp = client.get("/api/performance/benchmark")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "PASS"
    benchmarks = data["benchmarks"]

    # SLAs
    assert benchmarks["meets_inference_sla"] is True
    assert benchmarks["model_inference_latency_ms"] < 10.0
    assert benchmarks["meets_database_sla"] is True
    assert benchmarks["database_query_latency_ms"] < 20.0

    # Compression verification
    comp = benchmarks["compression_efficiency"]
    assert comp["raw_bytes"] > comp["compressed_bytes"]
    assert comp["bandwidth_reduction_pct"] > 30.0


def test_06_compound_indexes_present():
    """Ensures compound indexes are correctly declared on Payment and AuditEvent SQLAlchemy models."""
    payment_index_names = {idx.name for idx in Payment.__table__.indexes}
    assert "ix_payments_merchant_status_created" in payment_index_names
    assert "ix_payments_merchant_recovery_status" in payment_index_names

    # Check columns on Payment indexes
    for idx in Payment.__table__.indexes:
        if idx.name == "ix_payments_merchant_status_created":
            col_names = [col.name for col in idx.columns]
            assert col_names == ["merchant_id", "status", "created_at"]
        elif idx.name == "ix_payments_merchant_recovery_status":
            col_names = [col.name for col in idx.columns]
            assert col_names == ["merchant_id", "recovery_status"]

    audit_index_names = {idx.name for idx in AuditEvent.__table__.indexes}
    assert "ix_audit_payment_timestamp" in audit_index_names
    assert "ix_audit_event_type_timestamp" in audit_index_names

    # Check columns on AuditEvent indexes
    for idx in AuditEvent.__table__.indexes:
        if idx.name == "ix_audit_payment_timestamp":
            col_names = [col.name for col in idx.columns]
            assert col_names == ["payment_id", "timestamp"]
        elif idx.name == "ix_audit_event_type_timestamp":
            col_names = [col.name for col in idx.columns]
            assert col_names == ["event_type", "timestamp"]
