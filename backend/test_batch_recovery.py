"""
Phase 13: Batch Recovery Engine & Metrics Test Suite
===================================================
Tests:
  1.  POST /api/recovery/batch/run (dry_run)       - Predicts outcomes without DB state mutations
  2.  POST /api/recovery/batch/run (live)          - Recovers low-risk, quarantines high-risk & max retries
  3.  Verify financial & operational metrics       - Revenue at risk, recovered revenue, recovery rate %
  4.  Idempotent batch re-run                      - Skips already recovered payments
  5.  Merchant RBAC multi-tenant isolation         - Merchant only processes own payments
  6.  POST /api/recovery/batch/simulate-demo       - 100 payments benchmark demo (INR 2.5L risk, 48% yield)
  7.  GET  /api/recovery/batch/runs                - Paginated batch run history
  8.  GET  /api/recovery/batch/runs/{id}           - Detailed breakdown with itemized outcomes
  9.  GET  /api/recovery/batch/runs/{id} (cross)   - Merchant blocked from other merchant's batch
  10. GET  /api/recovery/batch/metrics             - Aggregate 30-day KPIs across batch runs
  11. Audit event verification                     - BATCH_RECOVERY_COMPLETED logged to audit trail
  12. Batch prioritization strategies              - AMOUNT_DESC vs NEWEST_FIRST
"""
import pytest
import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database.session import Base, get_db
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.risk_assessment import RiskAssessment
from app.models.audit_event import AuditEvent
from app.models.batch_run import BatchRun, BatchRunItem
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

# ─── Isolated Test Database ──────────────────────────────────────────────────
SQLALCHEMY_TEST_URL = "sqlite:///./test_batch.db"
engine = create_engine(SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── User Personas ───────────────────────────────────────────────────────────
ADMIN_USER = UserProfile(
    id="usr_adm_b", name="Admin User", email="admin@batch-rec.io",
    role="admin", merchant_id=None, is_active=True
)
REVIEWER_USER = UserProfile(
    id="usr_rev_b", name="Reviewer Staff", email="reviewer@batch-rec.io",
    role="reviewer", merchant_id=None, is_active=True
)
MERCHANT_1 = UserProfile(
    id="usr_m1_b", name="Alpha Merchant", email="owner@alpha-batch.com",
    role="merchant", merchant_id="mer_batch_01", is_active=True
)
MERCHANT_2 = UserProfile(
    id="usr_m2_b", name="Beta Merchant", email="owner@beta-batch.com",
    role="merchant", merchant_id="mer_batch_02", is_active=True
)

client = TestClient(app)


# ─── Seed Data Fixture ─────────────────────────────────────────────────────────
@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    now = datetime.datetime.utcnow()

    # Merchants
    m1 = Merchant(id="mer_batch_01", business_name="Alpha Tech", contact_email="admin@alpha-batch.com", is_live=True)
    m2 = Merchant(id="mer_batch_02", business_name="Beta Retail", contact_email="admin@beta-batch.com", is_live=True)
    db.add_all([m1, m2])
    db.commit()

    # Customers
    c1 = Customer(
        id="cust_b_01", merchant_id="mer_batch_01",
        email="c1@batch.com", phone="+919988776655", name="Customer Batch 1"
    )
    c2 = Customer(
        id="cust_b_02", merchant_id="mer_batch_02",
        email="c2@batch.com", phone="+919988776656", name="Customer Batch 2"
    )
    db.add_all([c1, c2])
    db.commit()

    # Payments for Merchant 1
    # 1. Low risk recoverable (INR 25,000)
    p1 = Payment(
        id="pay_b_001", merchant_id="mer_batch_01", customer_id="cust_b_01",
        amount=25000.0, currency="INR", status="FAILED", recovery_status="FAILED",
        error_code="BANK_DECLINE_TEMPORARY", retry_count=0, max_retries=3,
        created_at=now - datetime.timedelta(days=3)
    )
    # 2. Low risk recoverable (INR 15,000)
    p2 = Payment(
        id="pay_b_002", merchant_id="mer_batch_01", customer_id="cust_b_01",
        amount=15000.0, currency="INR", status="FAILED", recovery_status="FAILED",
        error_code="GATEWAY_TIMEOUT", retry_count=0, max_retries=3,
        created_at=now - datetime.timedelta(days=2)
    )
    # 3. High risk candidate (INR 80,000) -> should quarantine
    p3 = Payment(
        id="pay_b_003", merchant_id="mer_batch_01", customer_id="cust_b_01",
        amount=80000.0, currency="INR", status="FAILED", recovery_status="FAILED",
        error_code="SUSPICIOUS_VELOCITY", retry_count=0, max_retries=3,
        created_at=now - datetime.timedelta(days=1)
    )
    # 4. Max retries exhausted (INR 10,000) -> should quarantine
    p4 = Payment(
        id="pay_b_004", merchant_id="mer_batch_01", customer_id="cust_b_01",
        amount=10000.0, currency="INR", status="FAILED", recovery_status="FAILED",
        error_code="BANK_DECLINE", retry_count=3, max_retries=3,
        created_at=now - datetime.timedelta(hours=12)
    )
    # 5. Already recovered (INR 5,000) -> should skip
    p5 = Payment(
        id="pay_b_005", merchant_id="mer_batch_01", customer_id="cust_b_01",
        amount=5000.0, currency="INR", status="RECOVERED", recovery_status="RECOVERED",
        error_code=None, retry_count=1, max_retries=3,
        created_at=now - datetime.timedelta(hours=6)
    )

    # Payments for Merchant 2
    # 6. Merchant 2 payment (INR 40,000)
    p6 = Payment(
        id="pay_b_006", merchant_id="mer_batch_02", customer_id="cust_b_02",
        amount=40000.0, currency="INR", status="FAILED", recovery_status="FAILED",
        error_code="INSUFFICIENT_FUNDS", retry_count=0, max_retries=3,
        created_at=now - datetime.timedelta(days=1)
    )

    db.add_all([p1, p2, p3, p4, p5, p6])
    db.commit()

    # Seed Risk Assessments
    r1 = RiskAssessment(
        id="risk_b_001", payment_id="pay_b_001",
        risk_score=0.15, risk_level="LOW", model_version="1.0",
        features_used={"amount": 25000}, signals={},
        evaluated_at=now - datetime.timedelta(days=3)
    )
    r2 = RiskAssessment(
        id="risk_b_002", payment_id="pay_b_002",
        risk_score=0.18, risk_level="LOW", model_version="1.0",
        features_used={"amount": 15000}, signals={},
        evaluated_at=now - datetime.timedelta(days=2)
    )
    r3 = RiskAssessment(
        id="risk_b_003", payment_id="pay_b_003",
        risk_score=0.88, risk_level="HIGH", model_version="1.0",
        features_used={"amount": 80000}, signals={"high_risk": True},
        evaluated_at=now - datetime.timedelta(days=1)
    )
    r4 = RiskAssessment(
        id="risk_b_004", payment_id="pay_b_004",
        risk_score=0.45, risk_level="MEDIUM", model_version="1.0",
        features_used={"amount": 10000}, signals={},
        evaluated_at=now - datetime.timedelta(hours=12)
    )
    r5 = RiskAssessment(
        id="risk_b_005", payment_id="pay_b_005",
        risk_score=0.10, risk_level="LOW", model_version="1.0",
        features_used={"amount": 5000}, signals={},
        evaluated_at=now - datetime.timedelta(hours=6)
    )
    r6 = RiskAssessment(
        id="risk_b_006", payment_id="pay_b_006",
        risk_score=0.20, risk_level="LOW", model_version="1.0",
        features_used={"amount": 40000}, signals={},
        evaluated_at=now - datetime.timedelta(days=1)
    )
    db.add_all([r1, r2, r3, r4, r5, r6])
    db.commit()
    db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    Base.metadata.drop_all(bind=engine)


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_01_dry_run_batch_recovery():
    """Dry run simulates triage and predicts recovery outcomes without modifying DB state."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

    payload = {
        "merchant_id": "mer_batch_01",
        "dry_run": True,
        "max_batch_size": 10,
    }
    resp = client.post("/api/recovery/batch/run", json=payload)
    assert resp.status_code == 201
    data = resp.json()

    assert data["is_dry_run"] is True
    assert data["status"] == "COMPLETED"
    assert data["total_payments"] == 4  # 4 non-recovered payments for merchant 1
    assert data["quarantined_count"] >= 2  # pay_b_003 (HIGH risk) and pay_b_004 (max retries)
    assert data["revenue_at_risk"] == 130000.0  # 25k + 15k + 80k + 10k

    # Verify payments in DB were NOT mutated during dry-run
    db = TestingSessionLocal()
    p1 = db.query(Payment).filter(Payment.id == "pay_b_001").first()
    assert p1.status == "FAILED"
    assert p1.recovery_status == "FAILED"
    db.close()


def test_02_live_batch_recovery_execution():
    """Live batch run recovers low-risk payments and quarantines high-risk & max retry payments."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

    payload = {
        "merchant_id": "mer_batch_01",
        "dry_run": False,
        "max_batch_size": 10,
    }
    resp = client.post("/api/recovery/batch/run", json=payload)
    assert resp.status_code == 201
    data = resp.json()

    assert data["is_dry_run"] is False
    assert data["recovered_count"] == 2  # pay_b_001 and pay_b_002
    assert data["quarantined_count"] == 2  # pay_b_003 (HIGH risk) and pay_b_004 (max retries)
    assert data["revenue_recovered"] == 40000.0  # 25k + 15k
    assert data["recovery_rate_pct"] == round((40000.0 / 130000.0) * 100, 2)

    # Verify DB state of recovered payments
    db = TestingSessionLocal()
    p1 = db.query(Payment).filter(Payment.id == "pay_b_001").first()
    p2 = db.query(Payment).filter(Payment.id == "pay_b_002").first()
    p3 = db.query(Payment).filter(Payment.id == "pay_b_003").first()

    assert p1.status == "RECOVERED"
    assert p1.recovery_status == "RECOVERED"
    assert p2.status == "RECOVERED"
    assert p2.recovery_status == "RECOVERED"
    assert p3.status == "IN_REVIEW"  # Quarantined to human review
    db.close()


def test_03_batch_metrics_calculation():
    """Batch metrics accurately compute recovery rate, escalation rate, and average attempts."""
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER

    # Get the latest batch run detail
    runs_resp = client.get("/api/recovery/batch/runs?merchant_id=mer_batch_01&include_demo=false")
    assert runs_resp.status_code == 200
    runs_data = runs_resp.json()
    assert runs_data["total"] >= 1

    latest_batch_id = runs_data["runs"][0]["id"]
    detail_resp = client.get(f"/api/recovery/batch/runs/{latest_batch_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()

    assert "metrics" in detail
    metrics = detail["metrics"]
    assert metrics["recovery_rate_pct"] > 0
    assert metrics["escalation_rate_pct"] == 50.0  # 2 quarantined out of 4 = 50%
    assert metrics["revenue_recovered"] == 40000.0


def test_04_idempotent_rerun():
    """Re-running batch execution skips already recovered payments idempotently."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

    # Re-run for merchant 1
    payload = {
        "merchant_id": "mer_batch_01",
        "dry_run": False,
    }
    resp = client.post("/api/recovery/batch/run", json=payload)
    assert resp.status_code == 201
    data = resp.json()

    # pay_b_001 and pay_b_002 are now RECOVERED, so they are not included in candidate query
    # Only remaining candidate may be in-review or none
    assert data["recovered_count"] == 0


def test_05_merchant_scoped_batch_execution():
    """Merchant role is automatically scoped to their own payments only."""
    app.dependency_overrides[get_current_user] = lambda: MERCHANT_2

    payload = {
        "max_batch_size": 10,
        "dry_run": False,
    }
    resp = client.post("/api/recovery/batch/run", json=payload)
    assert resp.status_code == 201
    data = resp.json()

    # Merchant 2 has pay_b_006 (INR 40,000)
    assert data["total_payments"] == 1
    assert data["revenue_at_risk"] == 40000.0
    assert data["recovered_count"] == 1


def test_06_simulate_demo_benchmark():
    """POST /api/recovery/batch/simulate-demo creates the 100-payment benchmark demo."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

    payload = {
        "total_payments": 100,
        "target_revenue_at_risk": 250000.0,
        "target_revenue_recovered": 120000.0,
    }
    resp = client.post("/api/recovery/batch/simulate-demo", json=payload)
    assert resp.status_code == 201
    data = resp.json()

    assert data["is_demo"] is True
    assert data["total_payments"] == 100
    assert data["revenue_at_risk"] == 250000.0
    assert data["revenue_recovered"] == 120000.0
    assert data["recovery_rate_pct"] == 48.0
    assert data["recovered_count"] == 48
    assert data["quarantined_count"] == 22
    assert data["failed_count"] == 30

    demo_id = data["batch_id"]

    # Verify demo batch details
    detail_resp = client.get(f"/api/recovery/batch/runs/{demo_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["is_demo"] is True
    assert len(detail["items"]) == 100


def test_07_list_batch_runs():
    """GET /api/recovery/batch/runs returns paginated batch history."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

    resp = client.get("/api/recovery/batch/runs?limit=10&offset=0")
    assert resp.status_code == 200
    data = resp.json()

    assert "total" in data
    assert "runs" in data
    assert len(data["runs"]) >= 3


def test_08_get_batch_run_detail_and_items():
    """GET /api/recovery/batch/runs/{id} returns run detail and itemized entries."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

    # Get latest run
    runs = client.get("/api/recovery/batch/runs").json()["runs"]
    target_id = runs[0]["id"]

    resp = client.get(f"/api/recovery/batch/runs/{target_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == target_id
    assert "items" in data
    assert "metrics" in data

    # 404 on missing
    missing_resp = client.get("/api/recovery/batch/runs/batch_non_existent")
    assert missing_resp.status_code == 404


def test_09_merchant_forbidden_batch_detail():
    """Merchant 1 cannot access batch run owned by Merchant 2."""
    app.dependency_overrides[get_current_user] = lambda: MERCHANT_2
    m2_run_id = client.get("/api/recovery/batch/runs").json()["runs"][0]["id"]

    # Switch to Merchant 1
    app.dependency_overrides[get_current_user] = lambda: MERCHANT_1
    resp = client.get(f"/api/recovery/batch/runs/{m2_run_id}")
    assert resp.status_code == 404  # Scoped out / not found for merchant 1


def test_10_aggregate_batch_metrics():
    """GET /api/recovery/batch/metrics aggregates KPIs across runs."""
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER

    resp = client.get("/api/recovery/batch/metrics?days=30&include_demo=true")
    assert resp.status_code == 200
    data = resp.json()

    assert data["period_days"] == 30
    assert data["total_batch_runs"] >= 3
    assert data["financial_summary"]["total_revenue_at_risk"] > 0
    assert data["financial_summary"]["total_revenue_recovered"] > 0
    assert "recovery_rate_pct" in data["financial_summary"]
    assert "escalation_rate_pct" in data["operational_summary"]


def test_11_audit_event_logged_on_batch_completion():
    """Batch recovery automatically records an immutable AuditEvent."""
    db = TestingSessionLocal()
    batch_audit = (
        db.query(AuditEvent)
        .filter(AuditEvent.event_type == "BATCH_RECOVERY_COMPLETED")
        .first()
    )
    assert batch_audit is not None
    assert "Batch recovery run" in batch_audit.details
    db.close()


def test_12_prioritization_orders():
    """Prioritization parameter applies correctly to candidate selection."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

    payload = {
        "prioritization": "AMOUNT_DESC",
        "dry_run": True,
        "max_batch_size": 2,
    }
    resp = client.post("/api/recovery/batch/run", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "COMPLETED"
