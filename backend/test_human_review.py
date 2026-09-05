"""
Phase 10: Human Review & Escalation Queue Test Suite
=====================================================
Tests:
  1.  POST /api/review/quarantine/{payment_id}      - quarantine a HIGH-risk payment
  2.  POST /api/review/quarantine/{payment_id}      - idempotency (ALREADY_EXISTS)
  3.  POST /api/review/quarantine/{payment_id}      - merchant role gets 403
  4.  GET  /api/review/queue                        - PENDING queue contains quarantined payment
  5.  GET  /api/review/stats                        - stats shows 1 pending
  6.  GET  /api/review/{review_id}                  - full detail with AI diagnosis
  7.  POST /api/review/{review_id}/decision APPROVE - payment moves to FAILED
  8.  POST /api/review/{review_id}/decision (re-submit blocked) - 422
  9.  POST /api/review/auto-quarantine              - batch quarantines eligible payments
  10. GET  /api/review/queue (APPROVED)             - approved queue shows resolved review
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
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

# ─── In-Memory DB ─────────────────────────────────────────────────────────────
SQLALCHEMY_TEST_URL = "sqlite:///./test_review.db"
engine = create_engine(SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

# ─── User Personas ─────────────────────────────────────────────────────────────
REVIEWER_USER = UserProfile(
    id="usr_reviewer_001",
    name="Alex Risk Officer",
    email="reviewer@test.com",
    role="reviewer",
    merchant_id=None,
    is_active=True,
)
MERCHANT_USER = UserProfile(
    id="usr_merchant_001",
    name="Merchant Test",
    email="merchant@test.com",
    role="merchant",
    merchant_id="mer_review_test",
    is_active=True,
)
ADMIN_USER = UserProfile(
    id="usr_admin_001",
    name="Admin Test",
    email="admin@test.com",
    role="admin",
    merchant_id=None,
    is_active=True,
)

# ─── Seed Data ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    merchant = Merchant(
        id="mer_review_test",
        business_name="Review Test Co",
        contact_email="review@test.com",
        is_live=False,
    )
    db.add(merchant)

    customer = Customer(
        id="cust_review_01",
        merchant_id="mer_review_test",
        email="customer@review.com",
        name="Review Customer",
        lifetime_successful_orders=0,
        dispute_count=2,
        total_spend=500.0,
    )
    db.add(customer)
    db.flush()

    # pay_rv_001 — HIGH risk, should be quarantined
    p1 = Payment(
        id="pay_rv_001",
        merchant_id="mer_review_test",
        customer_id="cust_review_01",
        amount=75000.0,
        currency="INR",
        status="FAILED",
        error_code="CARD_VELOCITY_EXCEEDED",
        retry_count=3,
        max_retries=3,
        recovery_status="FAILED",
    )
    # pay_rv_002 — LOW risk, for auto-quarantine test (won't be auto-queued)
    p2 = Payment(
        id="pay_rv_002",
        merchant_id="mer_review_test",
        customer_id="cust_review_01",
        amount=1200.0,
        currency="INR",
        status="FAILED",
        error_code="BANK_DECLINE_TEMPORARY",
        retry_count=1,
        max_retries=3,
        recovery_status="FAILED",
    )
    # pay_rv_003 — ambiguous PROCESSING status for auto-quarantine
    p3 = Payment(
        id="pay_rv_003",
        merchant_id="mer_review_test",
        customer_id="cust_review_01",
        amount=9500.0,
        currency="INR",
        status="PROCESSING",
        error_code="GATEWAY_ERROR",
        retry_count=0,
        max_retries=3,
        recovery_status="FAILED",
    )
    db.add_all([p1, p2, p3])
    db.flush()

    # Risk assessments
    db.add(RiskAssessment(
        id="ra_rv_001",
        payment_id="pay_rv_001",
        risk_score=0.95,
        risk_level="HIGH",
        model_version="test-v1",
        features_used={"velocity_score": 0.90},
        signals=["High Card Velocity"],
    ))
    db.add(RiskAssessment(
        id="ra_rv_002",
        payment_id="pay_rv_002",
        risk_score=0.12,
        risk_level="LOW",
        model_version="test-v1",
        features_used={},
        signals=[],
    ))
    db.commit()
    db.close()
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    Base.metadata.drop_all(bind=engine)


# ─── State shared across tests ────────────────────────────────────────────────
state = {}


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_01_quarantine_payment():
    """Reviewer can quarantine a HIGH-risk payment."""
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER
    client = TestClient(app)
    res = client.post(
        "/api/review/quarantine/pay_rv_001",
        json={"reason": "Card velocity exceeded: flagged by risk engine for manual review."},
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["status"] == "CREATED"
    assert data["payment_id"] == "pay_rv_001"
    assert "review_id" in data
    state["review_id"] = data["review_id"]
    print(f"\n  [PASS] Quarantine: review_id={data['review_id']}, status={data['status']}")


def test_02_quarantine_idempotency():
    """Re-quarantining the same payment returns ALREADY_EXISTS, not a duplicate."""
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER
    client = TestClient(app)
    res = client.post(
        "/api/review/quarantine/pay_rv_001",
        json={"reason": "Second attempt to quarantine same payment."},
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["status"] == "ALREADY_EXISTS"
    assert data["review_id"] == state["review_id"]
    print(f"  [PASS] Idempotency: returned ALREADY_EXISTS with same review_id")


def test_03_merchant_cannot_quarantine():
    """Merchant role must be blocked (403 Forbidden)."""
    app.dependency_overrides[get_current_user] = lambda: MERCHANT_USER
    client = TestClient(app)
    res = client.post(
        "/api/review/quarantine/pay_rv_001",
        json={"reason": "Merchant trying to quarantine."},
    )
    assert res.status_code == 403, res.text
    print("  [PASS] Merchant blocked from quarantine (403)")


def test_04_get_review_queue():
    """PENDING queue should contain the quarantined payment."""
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER
    client = TestClient(app)
    res = client.get("/api/review/queue?queue_status=PENDING")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total"] >= 1
    ids = [item["payment_id"] for item in data["items"]]
    assert "pay_rv_001" in ids
    print(f"  [PASS] Queue: {data['total']} PENDING reviews, found pay_rv_001")


def test_05_queue_stats():
    """Stats should reflect at least 1 PENDING review."""
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER
    client = TestClient(app)
    res = client.get("/api/review/stats?days=30")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["queue_depth"] >= 1
    assert "resolution" in data
    assert data["resolution"]["pending"] >= 1
    print(f"  [PASS] Stats: queue_depth={data['queue_depth']}, resolution={data['resolution']}")


def test_06_get_review_detail():
    """Full detail should include payment, risk assessment, and AI diagnosis."""
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER
    client = TestClient(app)
    res = client.get(f"/api/review/{state['review_id']}")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["review"]["id"] == state["review_id"]
    assert data["review"]["status"] == "PENDING"
    assert data["payment"]["id"] == "pay_rv_001"
    assert data["risk_assessment"]["risk_level"] == "HIGH"
    assert data["ai_diagnosis"] is not None
    assert "category" in data["ai_diagnosis"]
    assert "recommended_action" in data["ai_diagnosis"]
    print(f"  [PASS] Detail: diagnosis_category={data['ai_diagnosis']['category']}, risk=HIGH")


def test_07_submit_approve_decision():
    """Reviewer APPROVE moves payment back to FAILED for automated retry."""
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER
    client = TestClient(app)
    res = client.post(
        f"/api/review/{state['review_id']}/decision",
        json={"decision": "APPROVE", "notes": "Legitimate high-value customer — approved for retry."},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["decision"] == "APPROVE"
    assert data["new_payment_status"] == "FAILED"
    assert data["reviewer_id"] == REVIEWER_USER.id
    print(f"  [PASS] Decision APPROVE: payment -> {data['new_payment_status']}")


def test_08_resubmit_decision_blocked():
    """Submitting a decision on an already-resolved review must return 422."""
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER
    client = TestClient(app)
    res = client.post(
        f"/api/review/{state['review_id']}/decision",
        json={"decision": "REJECT", "notes": "Trying to reject an already-approved review."},
    )
    assert res.status_code == 422, res.text
    print("  [PASS] Re-submit blocked on resolved review (422)")


def test_09_auto_quarantine_batch():
    """Auto-quarantine should queue pay_rv_003 (PROCESSING status) but not pay_rv_002 (LOW risk)."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    res = client.post("/api/review/auto-quarantine")
    assert res.status_code == 200, res.text
    data = res.json()
    payment_ids = [r["payment_id"] for r in data["results"]]
    assert "pay_rv_003" in payment_ids
    # pay_rv_002 is LOW risk and FAILED → should not be auto-queued
    assert "pay_rv_002" not in payment_ids
    print(f"  [PASS] Auto-quarantine: {data['quarantined_count']} quarantined, pay_rv_003 queued")


def test_10_approved_queue():
    """APPROVED queue should now contain the approved review."""
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER
    client = TestClient(app)
    res = client.get("/api/review/queue?queue_status=APPROVED")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total"] >= 1
    ids = [item["payment_id"] for item in data["items"]]
    assert "pay_rv_001" in ids
    print(f"  [PASS] APPROVED queue: {data['total']} resolved, pay_rv_001 present")
