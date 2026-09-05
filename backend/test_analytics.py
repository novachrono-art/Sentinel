"""
Phase 9: Analytics & Merchant Dashboard API Test Suite
========================================================
Tests all 7 analytics endpoints:
  1. GET /api/analytics/summary
  2. GET /api/analytics/failure-breakdown
  3. GET /api/analytics/risk-distribution
  4. GET /api/analytics/action-performance
  5. GET /api/analytics/daily-trend
  6. GET /api/analytics/top-risk-customers
  7. GET /api/analytics/merchant-leaderboard
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database.session import Base, get_db
from app.models.payment import Payment
from app.models.customer import Customer
from app.models.merchant import Merchant
from app.models.risk_assessment import RiskAssessment
from app.models.recovery_action import RecoveryAction
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

# ─── In-Memory DB Setup ───────────────────────────────────────────────────────
SQLALCHEMY_TEST_URL = "sqlite:///./test_analytics.db"
engine = create_engine(SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

# Two user personas for RBAC tests
ADMIN_USER = UserProfile(
    id="usr_admin_test",
    name="Admin Test",
    email="admin@test.com",
    role="admin",
    merchant_id=None,
    is_active=True,
)
MERCHANT_USER = UserProfile(
    id="usr_merchant_test",
    name="Merchant Test",
    email="merchant@test.com",
    role="merchant",
    merchant_id="mer_test_analytics",
    is_active=True,
)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    # Seed merchant
    merchant = Merchant(
        id="mer_test_analytics",
        business_name="Analytics Test Co",
        contact_email="analytics@test.com",
        is_live=False,
    )
    db.add(merchant)

    # Seed customer
    customer = Customer(
        id="cust_analytics_01",
        merchant_id="mer_test_analytics",
        email="buyer@example.com",
        name="Test Buyer",
        lifetime_successful_orders=5,
        dispute_count=0,
        total_spend=15000.0,
    )
    db.add(customer)
    db.flush()

    # Seed payments: 3 FAILED, 2 RECOVERED
    payments_data = [
        ("pay_an_001", "FAILED",     5000.0, "INSUFFICIENT_FUNDS"),
        ("pay_an_002", "FAILED",    12000.0, "CARD_VELOCITY_EXCEEDED"),
        ("pay_an_003", "FAILED",     3500.0, "GATEWAY_ERROR"),
        ("pay_an_004", "RECOVERED",  5000.0, "INSUFFICIENT_FUNDS"),
        ("pay_an_005", "RECOVERED", 12000.0, "CARD_VELOCITY_EXCEEDED"),
    ]
    for pid, status_val, amount, error_code in payments_data:
        p = Payment(
            id=pid,
            merchant_id="mer_test_analytics",
            customer_id="cust_analytics_01",
            amount=amount,
            currency="INR",
            status=status_val,
            error_code=error_code,
            retry_count=1,
            max_retries=3,
            recovery_status=status_val,
        )
        db.add(p)

    db.flush()

    # Seed risk assessments for all 5 payments
    risk_data = [
        ("pay_an_001", 0.40, "MEDIUM"),
        ("pay_an_002", 0.95, "HIGH"),
        ("pay_an_003", 0.25, "LOW"),
        ("pay_an_004", 0.40, "MEDIUM"),
        ("pay_an_005", 0.95, "HIGH"),
    ]
    for pid, score, level in risk_data:
        r = RiskAssessment(
            id=f"ra_{pid}",
            payment_id=pid,
            risk_score=score,
            risk_level=level,
            model_version="test-v1",
            features_used={},
            signals=[],
        )
        db.add(r)

    # Seed recovery actions for RECOVERED payments
    for pid in ["pay_an_004", "pay_an_005"]:
        a = RecoveryAction(
            id=f"act_{pid}",
            payment_id=pid,
            action_type="RETRY",
            idempotency_key=f"idem_{pid}",
            status="EXECUTED",
            payload={},
            execution_result={"gateway_status": "SUCCESS"},
        )
        db.add(a)

    db.commit()
    db.close()
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    Base.metadata.drop_all(bind=engine)


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_summary_admin():
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    res = client.get("/api/analytics/summary?days=30")
    assert res.status_code == 200, res.text
    data = res.json()
    assert "payments" in data
    assert "revenue" in data
    assert "rates" in data
    assert "risk" in data
    assert data["payments"]["failed"] == 3
    assert data["payments"]["recovered"] == 2
    assert data["rates"]["payment_recovery_rate_pct"] == 66.67
    print(f"\n  [PASS] Summary: recovery_rate={data['rates']['payment_recovery_rate_pct']}%")


def test_summary_merchant_isolation():
    """Merchant role sees data scoped to their merchant_id."""
    app.dependency_overrides[get_current_user] = lambda: MERCHANT_USER
    client = TestClient(app)
    res = client.get("/api/analytics/summary?days=30")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["payments"]["failed"] == 3
    print(f"  [PASS] Merchant-scoped summary: {data['payments']['failed']} failed payments")


def test_failure_breakdown():
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    res = client.get("/api/analytics/failure-breakdown?days=30")
    assert res.status_code == 200, res.text
    data = res.json()
    breakdown = data["breakdown"]
    assert isinstance(breakdown, list)
    assert len(breakdown) >= 2
    codes = [b["error_code"] for b in breakdown]
    assert "INSUFFICIENT_FUNDS" in codes
    assert "CARD_VELOCITY_EXCEEDED" in codes
    print(f"  [PASS] Failure breakdown: {len(breakdown)} error codes")


def test_risk_distribution():
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    res = client.get("/api/analytics/risk-distribution?days=30")
    assert res.status_code == 200, res.text
    data = res.json()
    distribution = data["distribution"]
    assert isinstance(distribution, list)
    levels = {d["risk_level"] for d in distribution}
    assert "HIGH" in levels
    total_pct = sum(d["percentage"] for d in distribution)
    assert abs(total_pct - 100.0) < 0.1
    print(f"  [PASS] Risk distribution: levels={levels}, total_pct={round(total_pct, 2)}%")


def test_action_performance():
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    res = client.get("/api/analytics/action-performance?days=30")
    assert res.status_code == 200, res.text
    data = res.json()
    perf = data["action_performance"]
    assert isinstance(perf, list)
    assert len(perf) >= 1
    retry_row = next((p for p in perf if p["action_type"] == "RETRY"), None)
    assert retry_row is not None
    assert retry_row["succeeded"] == 2
    assert retry_row["success_rate_pct"] == 100.0
    print(f"  [PASS] Action performance: RETRY success_rate={retry_row['success_rate_pct']}%")


def test_daily_trend():
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    res = client.get("/api/analytics/daily-trend?days=7")
    assert res.status_code == 200, res.text
    data = res.json()
    trend = data["trend"]
    assert len(trend) == 7
    for day in trend:
        assert "date" in day
        assert "failed_count" in day
        assert "recovered_count" in day
    print(f"  [PASS] Daily trend: {len(trend)} days returned")


def test_top_risk_customers():
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    res = client.get("/api/analytics/top-risk-customers?limit=5&days=30")
    assert res.status_code == 200, res.text
    data = res.json()
    customers = data["top_risk_customers"]
    assert isinstance(customers, list)
    assert len(customers) >= 1
    first = customers[0]
    assert "customer_id" in first
    assert "total_at_risk_inr" in first
    assert "average_risk_score" in first
    print(f"  [PASS] Top risk customers: {len(customers)} returned, top={first['customer_id']} at Rs.{first['total_at_risk_inr']}")


def test_merchant_leaderboard_admin():
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    res = client.get("/api/analytics/merchant-leaderboard?days=30")
    assert res.status_code == 200, res.text
    data = res.json()
    leaderboard = data["leaderboard"]
    assert isinstance(leaderboard, list)
    assert len(leaderboard) >= 1
    assert "merchant_id" in leaderboard[0]
    assert "revenue_recovery_rate_pct" in leaderboard[0]
    print(f"  [PASS] Merchant leaderboard: {len(leaderboard)} merchants")


def test_merchant_leaderboard_forbidden_for_merchant():
    """Merchants must NOT be able to call the leaderboard endpoint."""
    app.dependency_overrides[get_current_user] = lambda: MERCHANT_USER
    client = TestClient(app)
    res = client.get("/api/analytics/merchant-leaderboard?days=30")
    assert res.status_code == 403, res.text
    print("  [PASS] Merchant leaderboard correctly blocked for merchant role (403 Forbidden)")
