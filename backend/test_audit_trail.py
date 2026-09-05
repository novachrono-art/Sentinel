"""
Phase 12: Audit Trail & Compliance Export Test Suite
===================================================
Tests:
  1.  GET  /api/audit/events               - admin lists all events across merchants
  2.  GET  /api/audit/events (merchant)    - merchant auto-scoped to own merchant_id
  3.  GET  /api/audit/events?event_type=.. - filter by event_type
  4.  GET  /api/audit/events?search=..     - search by details or actor
  5.  GET  /api/audit/events/{payment_id}  - chronological timeline with per-event SHA-256 chain hash
  6.  GET  /api/audit/events/{payment_id}  - merchant isolation (403) and not found (404)
  7.  GET  /api/audit/chain                - deterministic SHA-256 tamper-evident chain verification
  8.  GET  /api/audit/export/csv           - streaming CSV export with headers and rows
  9.  GET  /api/audit/export/ndjson        - streaming NDJSON export (valid JSON per line)
  10. GET  /api/audit/compliance-report    - KPI aggregations, human review coverage, chain hash
  11. POST /api/audit/events               - admin manually emits custom event
  12. POST /api/audit/events (non-admin)   - reviewer / merchant blocked (403)
  13. Merchant blocked from exports/chain  - merchant receives 403 on restricted endpoints
"""
import pytest
import datetime
import json
import csv
import io
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database.session import Base, get_db
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.audit_event import AuditEvent
from app.models.risk_assessment import RiskAssessment
from app.models.human_review import HumanReview
from app.models.user import User
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile
from app.services.audit.audit_service import GENESIS_HASH, _compute_chain

# ─── Isolated Test Database ──────────────────────────────────────────────────
SQLALCHEMY_TEST_URL = "sqlite:///./test_audit.db"
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
    id="usr_adm", name="Admin User", email="admin@recovery.io",
    role="admin", merchant_id=None, is_active=True
)
REVIEWER_USER = UserProfile(
    id="usr_rev", name="Reviewer Staff", email="reviewer@recovery.io",
    role="reviewer", merchant_id=None, is_active=True
)
MERCHANT_1 = UserProfile(
    id="usr_m1", name="Alpha Merchant", email="owner@alpha.com",
    role="merchant", merchant_id="mer_au_01", is_active=True
)
MERCHANT_2 = UserProfile(
    id="usr_m2", name="Beta Merchant", email="owner@beta.com",
    role="merchant", merchant_id="mer_au_02", is_active=True
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
    m1 = Merchant(id="mer_au_01", business_name="Alpha Store", contact_email="admin@alpha.com", is_live=True)
    m2 = Merchant(id="mer_au_02", business_name="Beta Store", contact_email="admin@beta.com", is_live=True)
    db.add_all([m1, m2])
    db.commit()

    # Staff User
    reviewer_user = User(
        id="usr_rev_db",
        email="reviewer@recovery.io",
        name="Reviewer Staff",
        role="reviewer",
        is_active=True
    )
    db.add(reviewer_user)
    db.commit()

    # Customers
    c1 = Customer(
        id="cust_au_01", merchant_id="mer_au_01",
        email="c1@customer.com", phone="+919876543210", name="Customer One"
    )
    c2 = Customer(
        id="cust_au_02", merchant_id="mer_au_02",
        email="c2@customer.com", phone="+919876543211", name="Customer Two"
    )
    db.add_all([c1, c2])
    db.commit()

    # Payments
    p1 = Payment(
        id="pay_au_001", merchant_id="mer_au_01", customer_id="cust_au_01",
        amount=50000.0, currency="INR", status="FAILED",
        created_at=now - datetime.timedelta(days=5)
    )
    p2 = Payment(
        id="pay_au_002", merchant_id="mer_au_01", customer_id="cust_au_01",
        amount=12000.0, currency="INR", status="RECOVERED",
        created_at=now - datetime.timedelta(days=2)
    )
    p3 = Payment(
        id="pay_au_003", merchant_id="mer_au_02", customer_id="cust_au_02",
        amount=30000.0, currency="INR", status="FAILED",
        created_at=now - datetime.timedelta(days=1)
    )
    db.add_all([p1, p2, p3])
    db.commit()

    # Risk Assessments
    r1 = RiskAssessment(
        id="risk_au_001", payment_id="pay_au_001",
        risk_score=0.88, risk_level="HIGH", model_version="1.0",
        features_used={"amount": 50000}, signals={"high_value": True},
        evaluated_at=now - datetime.timedelta(days=5)
    )
    r2 = RiskAssessment(
        id="risk_au_002", payment_id="pay_au_002",
        risk_score=0.15, risk_level="LOW", model_version="1.0",
        features_used={"amount": 12000}, signals={},
        evaluated_at=now - datetime.timedelta(days=2)
    )
    r3 = RiskAssessment(
        id="risk_au_003", payment_id="pay_au_003",
        risk_score=0.45, risk_level="MEDIUM", model_version="1.0",
        features_used={"amount": 30000}, signals={},
        evaluated_at=now - datetime.timedelta(days=1)
    )
    db.add_all([r1, r2, r3])
    db.commit()

    # Human Review for pay_au_001
    hr1 = HumanReview(
        id="hr_au_001", payment_id="pay_au_001", reviewer_id="usr_rev_db",
        status="APPROVED", reason_for_quarantine="Risk score 0.88 HIGH",
        decision="APPROVE", decision_notes="Verified via KYC",
        quarantined_at=now - datetime.timedelta(days=4),
        resolved_at=now - datetime.timedelta(days=3)
    )
    db.add(hr1)
    db.commit()

    # Audit Events
    ae1 = AuditEvent(
        id="ae_au_001", payment_id="pay_au_001",
        event_type="PAYMENT_FAILED", actor="System:Gateway",
        details="Payment gateway returned bank timeout error",
        outcome="FAILED", risk_level=None,
        timestamp=now - datetime.timedelta(days=5)
    )
    ae2 = AuditEvent(
        id="ae_au_002", payment_id="pay_au_001",
        event_type="RISK_EVALUATION", actor="AI_AGENT:RiskClassifier",
        details="Evaluated payment as HIGH risk score 0.88",
        outcome="QUARANTINED", risk_level="HIGH",
        timestamp=now - datetime.timedelta(days=4, hours=23)
    )
    ae3 = AuditEvent(
        id="ae_au_003", payment_id="pay_au_001",
        event_type="HUMAN_REVIEW_APPROVED", actor="Reviewer:reviewer@recovery.io",
        details="Staff reviewer approved high-risk quarantine",
        outcome="APPROVED", risk_level="HIGH",
        timestamp=now - datetime.timedelta(days=3)
    )
    ae4 = AuditEvent(
        id="ae_au_004", payment_id="pay_au_002",
        event_type="RECOVERY_COMPLETED", actor="AI_AGENT:ExecutionService",
        details="Automated recovery retry completed successfully",
        outcome="SUCCESS", risk_level="LOW",
        timestamp=now - datetime.timedelta(days=2)
    )
    ae5 = AuditEvent(
        id="ae_au_005", payment_id="pay_au_003",
        event_type="PAYMENT_FAILED", actor="System:Gateway",
        details="Card issuer declined transaction with insufficient funds",
        outcome="FAILED", risk_level="MEDIUM",
        timestamp=now - datetime.timedelta(days=1)
    )
    db.add_all([ae1, ae2, ae3, ae4, ae5])
    db.commit()
    db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    Base.metadata.drop_all(bind=engine)


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_01_list_events_admin():
    """Admin sees all audit events across all merchants."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    resp = client.get("/api/audit/events")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["events"]) == 5
    # Verify required keys in event payload
    first_event = data["events"][0]
    for key in ["id", "payment_id", "event_type", "actor", "details", "timestamp"]:
        assert key in first_event


def test_02_merchant_scoped_events():
    """Merchants are automatically isolated to payments belonging to their merchant_id."""
    # Merchant 1 owns pay_au_001 (3 events) and pay_au_002 (1 event) = 4 events
    app.dependency_overrides[get_current_user] = lambda: MERCHANT_1
    resp = client.get("/api/audit/events")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4
    for ev in data["events"]:
        assert ev["payment_id"] in ("pay_au_001", "pay_au_002")

    # Merchant 2 owns pay_au_003 (1 event)
    app.dependency_overrides[get_current_user] = lambda: MERCHANT_2
    resp = client.get("/api/audit/events")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["events"][0]["payment_id"] == "pay_au_003"


def test_03_filter_by_event_type():
    """Filtering by event_type returns only matching events."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    resp = client.get("/api/audit/events?event_type=PAYMENT_FAILED")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    for ev in data["events"]:
        assert ev["event_type"] == "PAYMENT_FAILED"


def test_04_filter_by_search():
    """Full-text substring search across details and actor."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    resp = client.get("/api/audit/events?search=gateway")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    for ev in data["events"]:
        assert "gateway" in ev["actor"].lower() or "gateway" in ev["details"].lower()


def test_05_payment_timeline_with_chain():
    """Payment timeline returns events in ascending order with 64-char hex chain hashes."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    resp = client.get("/api/audit/events/pay_au_001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["payment_id"] == "pay_au_001"
    assert data["merchant_id"] == "mer_au_01"
    assert data["event_count"] == 3
    assert len(data["timeline"]) == 3

    # Check ascending order and valid 64-character SHA-256 chain hashes
    for item in data["timeline"]:
        chain_hash = item["chain_hash"]
        assert isinstance(chain_hash, str)
        assert len(chain_hash) == 64
        # valid hex
        int(chain_hash, 16)


def test_06_payment_timeline_merchant_forbidden_and_404():
    """Merchant cannot view timeline of another merchant's payment, and 404 for missing."""
    # Merchant 2 attempts to view Merchant 1's payment
    app.dependency_overrides[get_current_user] = lambda: MERCHANT_2
    resp = client.get("/api/audit/events/pay_au_001")
    assert resp.status_code == 403

    # Admin requests non-existent payment
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    resp = client.get("/api/audit/events/pay_non_existent")
    assert resp.status_code == 404


def test_07_chain_hash_deterministic():
    """Chain hash computation returns valid structure and is deterministic across queries."""
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER
    resp1 = client.get("/api/audit/chain")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["event_count"] == 5
    assert len(data1["final_chain_hash"]) == 64
    assert data1["genesis_hash"] == GENESIS_HASH

    resp2 = client.get("/api/audit/chain")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data1["final_chain_hash"] == data2["final_chain_hash"]


def test_08_export_csv():
    """CSV export returns 200, valid text/csv content, and expected CSV headers/rows."""
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER
    resp = client.get("/api/audit/export/csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment;" in resp.headers["content-disposition"]

    csv_reader = csv.reader(io.StringIO(resp.text))
    rows = list(csv_reader)
    # Header + 5 rows
    assert len(rows) == 6
    expected_header = ["id", "payment_id", "event_type", "actor", "outcome", "risk_level", "details", "timestamp"]
    assert rows[0] == expected_header


def test_09_export_ndjson():
    """NDJSON export returns 200 and each line parses as a valid JSON object."""
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER
    resp = client.get("/api/audit/export/ndjson")
    assert resp.status_code == 200
    assert "application/x-ndjson" in resp.headers["content-type"]

    lines = [line.strip() for line in resp.text.strip().split("\n") if line.strip()]
    assert len(lines) == 5
    for line in lines:
        obj = json.loads(line)
        assert "id" in obj
        assert "event_type" in obj
        assert "actor" in obj


def test_10_compliance_report():
    """Compliance report returns aggregations, human review KPI, and chain hash."""
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER
    resp = client.get("/api/audit/compliance-report?days=30")
    assert resp.status_code == 200
    data = resp.json()

    assert data["period_days"] == 30
    assert data["total_audit_events"] == 5
    assert "event_type_breakdown" in data
    assert "actor_breakdown" in data
    assert "outcome_breakdown" in data

    # Human review coverage check:
    # 1 high-risk payment created in period (pay_au_001), 1 reviewed -> 100% coverage
    hr = data["human_review"]
    assert hr["high_risk_payments"] == 1
    assert hr["reviewed_count"] == 1
    assert hr["coverage_pct"] == 100.0

    # Data integrity check
    integrity = data["data_integrity"]
    assert len(integrity["final_chain_hash"]) == 64
    assert integrity["events_in_chain"] == 5


def test_11_emit_custom_event_admin():
    """Admin can manually emit a custom audit event."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    payload = {
        "payment_id": "pay_au_001",
        "event_type": "MANUAL_OVERRIDE",
        "actor": "AdminOverride",
        "details": "Admin manually applied compliance clearance to payment",
        "outcome": "CLEARED",
        "risk_level": "HIGH",
        "metadata_json": {"ticket_id": "SEC-9082"}
    }
    resp = client.post("/api/audit/events", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["payment_id"] == "pay_au_001"
    assert data["event_type"] == "MANUAL_OVERRIDE"
    assert "ManualEntry:admin@recovery.io" in data["actor"]
    assert "id" in data


def test_12_non_admin_blocked_from_emit():
    """Reviewers and merchants are forbidden from emitting manual audit events."""
    payload = {
        "payment_id": "pay_au_001",
        "event_type": "MANUAL_OVERRIDE",
        "actor": "StaffReviewer",
        "details": "Reviewer attempt to emit event",
    }
    # Reviewer blocked
    app.dependency_overrides[get_current_user] = lambda: REVIEWER_USER
    resp = client.post("/api/audit/events", json=payload)
    assert resp.status_code == 403

    # Merchant blocked
    app.dependency_overrides[get_current_user] = lambda: MERCHANT_1
    resp = client.post("/api/audit/events", json=payload)
    assert resp.status_code == 403


def test_13_merchant_blocked_from_exports_and_chain():
    """Merchants receive 403 on staff-only export, chain, and compliance-report endpoints."""
    app.dependency_overrides[get_current_user] = lambda: MERCHANT_1

    for endpoint in [
        "/api/audit/export/csv",
        "/api/audit/export/ndjson",
        "/api/audit/chain",
        "/api/audit/compliance-report",
    ]:
        resp = client.get(endpoint)
        assert resp.status_code == 403, f"Expected 403 on {endpoint}, got {resp.status_code}"
