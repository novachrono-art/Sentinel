"""
Phase 14: Critical Failure Scenarios Test Suite
===============================================
Automated end-to-end verification of the 6 core scenarios:
  1.  Scenario 1: Successful Recovery   - Failed -> Low Risk -> Retry -> Success (RECOVERED)
  2.  Scenario 2: Retry Required        - Failed -> Low Risk -> Retry 1 Failed -> Retry 2 Success (RECOVERED)
  3.  Scenario 3: Retry Limit Cap       - Failed -> Retries Exhausted (3/3) -> STOP -> Human Review
  4.  Scenario 4: Risky Payment         - Failed -> High Risk (0.92) -> STOP -> Immediate Quarantine
  5.  Scenario 5: Unknown/Ambiguous     - Payment in PENDING_VERIFICATION -> STOP -> Fail Closed
  6.  Scenario 6: Duplicate Action      - Same Idempotency Key Twice -> Blocked & Suppressed
  7.  GET  /api/scenarios/catalog       - Scenario catalog retrieval
  8.  POST /api/scenarios/run-all       - Certified test runner executing all 6 scenarios
  9.  POST /api/scenarios/{num}/run     - Individual execution and validation
  10. Audit event verification          - Traceability proof in audit trail
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database.session import Base, get_db
from app.models.payment import Payment
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.audit_event import AuditEvent
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

# ─── Isolated Test Database ──────────────────────────────────────────────────
SQLALCHEMY_TEST_URL = "sqlite:///./test_scenarios.db"
engine = create_engine(SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


ADMIN_USER = UserProfile(
    id="usr_adm_scen", name="Admin User", email="admin@scenarios.io",
    role="admin", merchant_id=None, is_active=True
)

client = TestClient(app)


# ─── Seed Data Fixture ─────────────────────────────────────────────────────────
@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    m = Merchant(
        id="mer_scenario_test",
        business_name="Scenario Test Store",
        contact_email="test@scenarios.io",
        is_live=True
    )
    c = Customer(
        id="cust_scenario_test",
        merchant_id="mer_scenario_test",
        name="Scenario Test Customer",
        email="customer@scenarios.io",
        phone="+919876543299"
    )
    db.add_all([m, c])
    db.commit()
    db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

    yield

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    Base.metadata.drop_all(bind=engine)


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_01_scenario_catalog():
    """GET /api/scenarios/catalog returns all 6 scenarios with metadata."""
    resp = client.get("/api/scenarios/catalog")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 6
    assert len(data["scenarios"]) == 6
    for s in data["scenarios"]:
        assert "number" in s
        assert "name" in s
        assert "chain" in s
        assert "guardrail" in s


def test_02_scenario_1_successful_recovery():
    """Scenario 1: Failed -> Low Risk -> Direct Gateway Retry -> Success (RECOVERED)."""
    resp = client.post("/api/scenarios/1/run")
    assert resp.status_code == 200
    data = resp.json()

    assert data["scenario_id"] == "scenario_1_successful_recovery"
    assert data["passed"] is True
    assert data["final_status"] == "RECOVERED"
    assert data["action_executed"] == "RETRY"
    assert data["attempt_number"] == 1
    assert len(data["steps"]) == 5


def test_03_scenario_2_retry_required():
    """Scenario 2: Failed -> Low Risk -> Retry #1 Fails -> Retry #2 Succeeds (RECOVERED)."""
    resp = client.post("/api/scenarios/2/run")
    assert resp.status_code == 200
    data = resp.json()

    assert data["scenario_id"] == "scenario_2_retry_required"
    assert data["passed"] is True
    assert data["final_status"] == "RECOVERED"
    assert data["total_attempts"] == 2
    assert len(data["steps"]) == 5


def test_04_scenario_3_retry_limit():
    """Scenario 3: Failed -> Retries Exhausted (3/3) -> STOP & Auto-Quarantine to Human Review."""
    resp = client.post("/api/scenarios/3/run")
    assert resp.status_code == 200
    data = resp.json()

    assert data["scenario_id"] == "scenario_3_retry_limit"
    assert data["passed"] is True
    assert data["final_status"] == "IN_REVIEW"
    assert data["execution_status"] == "BLOCKED"
    assert "retry" in data["guardrail_block_reason"].lower()
    assert data["human_review_id"] is not None


def test_05_scenario_4_risky_payment():
    """Scenario 4: Failed -> High Risk (0.92) -> STOP -> Immediate Quarantine (Zero Gateway Touch)."""
    resp = client.post("/api/scenarios/4/run")
    assert resp.status_code == 200
    data = resp.json()

    assert data["scenario_id"] == "scenario_4_risky_payment"
    assert data["passed"] is True
    assert data["final_status"] == "IN_REVIEW"
    assert data["execution_status"] == "BLOCKED"
    assert data["risk_score"] == 0.92
    assert data["risk_level"] == "HIGH"
    assert data["human_review_id"] is not None


def test_06_scenario_5_unknown_state():
    """Scenario 5: Payment in PENDING_VERIFICATION -> STOP & Fail Closed (Prevent Double Charging)."""
    resp = client.post("/api/scenarios/5/run")
    assert resp.status_code == 200
    data = resp.json()

    assert data["scenario_id"] == "scenario_5_unknown_state"
    assert data["passed"] is True
    assert data["initial_status"] == "PENDING_VERIFICATION"
    assert data["final_status"] == "IN_REVIEW"
    assert data["execution_status"] == "ESCALATED"
    assert data["human_review_id"] is not None


def test_07_scenario_6_duplicate_action():
    """Scenario 6: Same Idempotency Key Twice -> 2nd Action Blocked (Zero Double Billing)."""
    resp = client.post("/api/scenarios/6/run")
    assert resp.status_code == 200
    data = resp.json()

    assert data["scenario_id"] == "scenario_6_duplicate_action"
    assert data["passed"] is True
    assert data["first_call"]["success"] is True
    assert data["second_call"]["success"] is False
    assert data["second_call"]["status"] == "BLOCKED"
    assert "Idempotency lock violation" in data["second_call"]["details"]


def test_08_run_all_scenarios_certificate():
    """POST /api/scenarios/run-all executes all 6 scenarios in sequence and certifies completion."""
    resp = client.post("/api/scenarios/run-all")
    assert resp.status_code == 200
    data = resp.json()

    assert data["all_passed"] is True
    assert data["total_scenarios"] == 6
    assert data["passed_count"] == 6
    assert data["failed_count"] == 0
    assert len(data["scenarios"]) == 6


def test_09_invalid_scenario_number():
    """POST /api/scenarios/99/run returns 400 Bad Request."""
    resp = client.post("/api/scenarios/99/run")
    assert resp.status_code == 400
    assert "Invalid scenario number" in resp.json()["detail"]


def test_10_audit_events_created_for_scenarios():
    """Executing scenarios creates auditable event trail entries."""
    db = TestingSessionLocal()
    events = db.query(AuditEvent).all()
    assert len(events) >= 5
    types = {e.event_type for e in events}
    assert "RECOVERY_ACTION_EXECUTED" in types
    db.close()
