"""
Phase 17: Interactive Demo Mode & Verification Showcase Test Suite
==================================================================
Tests:
  1. Seed Demo Environment: Exact ₹2,48,000 revenue at risk & 3 signature stories
  2. Story 1 (Happy Path): ₹4,999 recovery with Low Risk & Razorpay verification
  3. Story 2 (Safety Path): ₹35,000 quarantine with High Risk (0.92) & Zero Gateway Touch
  4. Story 3 (Retry Guardrail): Hard stop at 3 attempts & human escalation
  5. Demo State Reporting: Active status tracking of all three stories
  6. Demo Reset: Idempotent re-initialization to pristine ₹2.48L state
  7. System Certificate: Full 17-Phase verification and safety guarantee sign-off
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database.session import Base, get_db
from app.models.payment import Payment
from app.models.human_review import HumanReview
from app.models.audit_event import AuditEvent
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

# Isolated Test Database
SQLALCHEMY_TEST_URL = "sqlite:///./test_demo_mode.db"
engine = create_engine(SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


DEMO_ADMIN = UserProfile(
    id="usr_demo_admin",
    name="Lead Showcase Presenter",
    email="presenter@revrecover.io",
    role="admin",
    merchant_id="mer_demo_apex",
    is_active=True
)

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: DEMO_ADMIN

    yield

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    Base.metadata.drop_all(bind=engine)


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_01_seed_demo_environment():
    """POST /api/demo/seed sets up exact ₹2,48,000 revenue at risk across 7 payments."""
    resp = client.post("/api/demo/seed")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "INITIALIZED"
    assert data["merchant_id"] == "mer_demo_apex"
    assert data["business_name"] == "Apex Retail India Ltd"
    assert data["total_revenue_at_risk"] == 248000.0
    assert data["payments_seeded_count"] == 7
    assert len(data["stories_ready"]) == 3


def test_02_story_1_happy_path():
    """Story 1: ₹4,999 payment -> Low Risk (0.12) -> Gateway retry -> RECOVERED."""
    resp = client.post("/api/demo/step/happy-path")
    assert resp.status_code == 200
    data = resp.json()

    assert data["story"] == 1
    assert data["status"] == "COMPLETED"
    assert data["payment_id"] == "pay_demo_story1"
    assert data["amount_recovered"] == 4999.0
    assert data["outcome"] == "RECOVERED"
    assert len(data["steps"]) == 6

    # Verify database persistence
    db = TestingSessionLocal()
    p = db.query(Payment).filter(Payment.id == "pay_demo_story1").first()
    assert p.status == "RECOVERED"
    assert p.recovery_status == "RECOVERED"
    assert p.retry_count == 1

    # Verify audit events
    audits = db.query(AuditEvent).filter(AuditEvent.payment_id == "pay_demo_story1").all()
    event_types = {a.event_type for a in audits}
    assert "RECOVERY_EXECUTION_SUCCESS" in event_types
    assert "RISK_ASSESSMENT_COMPLETED" in event_types
    db.close()


def test_03_story_2_safety_path():
    """Story 2: ₹35,000 payment -> High Risk (0.92) -> Autonomous Block -> Quarantined."""
    resp = client.post("/api/demo/step/safety-path")
    assert resp.status_code == 200
    data = resp.json()

    assert data["story"] == 2
    assert data["status"] == "COMPLETED"
    assert data["payment_id"] == "pay_demo_story2"
    assert data["amount_quarantined"] == 35000.0
    assert data["risk_score"] == 0.92
    assert data["risk_level"] == "HIGH"
    assert data["outcome"] == "QUARANTINED_TO_HUMAN_REVIEW"

    # Verify database persistence
    db = TestingSessionLocal()
    p = db.query(Payment).filter(Payment.id == "pay_demo_story2").first()
    assert p.status == "IN_REVIEW"
    assert p.recovery_status == "IN_REVIEW"

    # Verify human review ticket created
    rev = db.query(HumanReview).filter(HumanReview.payment_id == "pay_demo_story2").first()
    assert rev is not None
    assert rev.status == "PENDING"
    assert "0.92" in rev.reason_for_quarantine

    # Verify audit events
    audits = db.query(AuditEvent).filter(AuditEvent.payment_id == "pay_demo_story2").all()
    event_types = {a.event_type for a in audits}
    assert "GUARDRAIL_BLOCKED" in event_types
    assert "HUMAN_REVIEW_QUARANTINED" in event_types
    db.close()


def test_04_story_3_retry_ceiling():
    """Story 3: 3/3 Retries reached -> Hard Stop -> Escalated to Human Review."""
    resp = client.post("/api/demo/step/retry-guardrail")
    assert resp.status_code == 200
    data = resp.json()

    assert data["story"] == 3
    assert data["status"] == "COMPLETED"
    assert data["payment_id"] == "pay_demo_story3"
    assert data["amount"] == 12500.0
    assert data["retries_exhausted"] == "3 / 3"
    assert data["outcome"] == "CEILING_EXHAUSTED_AND_ESCALATED"

    # Verify database persistence
    db = TestingSessionLocal()
    p = db.query(Payment).filter(Payment.id == "pay_demo_story3").first()
    assert p.status == "IN_REVIEW"
    assert p.retry_count == 3

    # Verify human review ticket
    rev = db.query(HumanReview).filter(HumanReview.payment_id == "pay_demo_story3").first()
    assert rev is not None
    assert "ceiling" in rev.reason_for_quarantine.lower()

    # Verify audit events
    audits = db.query(AuditEvent).filter(AuditEvent.payment_id == "pay_demo_story3").all()
    event_types = {a.event_type for a in audits}
    assert "RETRY_CEILING_EXHAUSTED" in event_types
    assert "ESCALATED_TO_HUMAN" in event_types
    db.close()


def test_05_demo_state_tracking():
    """GET /api/demo/state tracks execution and reflects recoveries and quarantined amounts."""
    resp = client.get("/api/demo/state")
    assert resp.status_code == 200
    data = resp.json()

    assert data["merchant_id"] == "mer_demo_apex"
    assert data["total_revenue_at_risk"] == 248000.0
    assert data["total_recovered_revenue"] == 4999.0
    assert data["pending_review_count"] >= 2

    stories = data["stories"]
    assert stories["story_1_happy_path"]["completed"] is True
    assert stories["story_2_safety_path"]["completed"] is True
    assert stories["story_3_retry_guardrail"]["completed"] is True


def test_06_demo_reset_clean():
    """POST /api/demo/reset wipes mutations and restores pristine initial ₹2.48L state."""
    resp = client.post("/api/demo/reset")
    assert resp.status_code == 200
    assert resp.json()["status"] == "INITIALIZED"

    # Check that stories are reset
    state_resp = client.get("/api/demo/state")
    state = state_resp.json()
    assert state["total_recovered_revenue"] == 0.0
    assert state["pending_review_count"] == 0
    assert state["stories"]["story_1_happy_path"]["completed"] is False
    assert state["stories"]["story_2_safety_path"]["completed"] is False
    assert state["stories"]["story_3_retry_guardrail"]["completed"] is False


def test_07_system_certificate_endpoint():
    """GET /api/demo/certificate validates 17-Phase architectural completion."""
    resp = client.get("/api/demo/certificate")
    assert resp.status_code == 200
    data = resp.json()

    assert data["overall_status"] == "ALL_17_PHASES_CERTIFIED"
    assert data["total_phases"] == 18  # Phase 0 to 17 = 18 phases
    assert data["phases_certified"] == 18
    assert data["total_unit_tests"] == 85
    assert len(data["key_safety_guarantees"]) >= 6
