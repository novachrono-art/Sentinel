"""
Phase 15: Security Hardening & Safety Protections Test Suite
===========================================================
Tests:
  1.  OWASP security headers presence on all HTTP responses
  2.  Identifier validation & SQLi / Path Traversal / XSS heuristic rejection
  3.  Secret credential & PAN masking recursive sanitizer
  4.  Execution sliding-window rate limiting & HTTP 429 Too Many Requests
  5.  Request payload size ceiling & HTTP 413 Payload Too Large
  6.  GET /api/security/audit posture check
  7.  Multi-tenant RBAC isolation (cross-merchant block)
  8.  Retry cap compliance (ceiling = 3)
  9.  Fail-closed ambiguity verification
  10. Prefix-specific identifier enforcement
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database.session import Base, get_db
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.payment import Payment
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile
from app.utils.security import (
    is_valid_identifier,
    sanitize_payload,
    SlidingWindowRateLimiter,
    execution_rate_limiter,
)
from app.services.recovery.execution_service import RecoveryExecutionService

# ─── Isolated Test Database ──────────────────────────────────────────────────
SQLALCHEMY_TEST_URL = "sqlite:///./test_security.db"
engine = create_engine(SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


ADMIN_USER = UserProfile(
    id="usr_adm_sec", name="Security Officer", email="sec@recovery.io",
    role="admin", merchant_id=None, is_active=True
)
MERCHANT_A = UserProfile(
    id="usr_mer_a_sec", name="Merchant A", email="a@sec.io",
    role="merchant", merchant_id="mer_sec_a", is_active=True
)
MERCHANT_B = UserProfile(
    id="usr_mer_b_sec", name="Merchant B", email="b@sec.io",
    role="merchant", merchant_id="mer_sec_b", is_active=True
)

client = TestClient(app)


# ─── Seed Data Fixture ─────────────────────────────────────────────────────────
@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    m_a = Merchant(id="mer_sec_a", business_name="Secure Store A", contact_email="a@sec.io", is_live=True)
    m_b = Merchant(id="mer_sec_b", business_name="Secure Store B", contact_email="b@sec.io", is_live=True)
    db.add_all([m_a, m_b])

    c_a = Customer(id="cust_sec_a", merchant_id="mer_sec_a", name="Customer A", email="cust_a@sec.io")
    c_b = Customer(id="cust_sec_b", merchant_id="mer_sec_b", name="Customer B", email="cust_b@sec.io")
    db.add_all([c_a, c_b])

    p_a = Payment(id="pay_sec_001", merchant_id="mer_sec_a", customer_id="cust_sec_a", amount=15000.0, status="FAILED")
    p_b = Payment(id="pay_sec_002", merchant_id="mer_sec_b", customer_id="cust_sec_b", amount=25000.0, status="FAILED")
    db.add_all([p_a, p_b])

    db.commit()
    db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

    yield

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    Base.metadata.drop_all(bind=engine)


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_01_security_headers_present():
    """All HTTP responses must contain OWASP-recommended security headers."""
    resp = client.get("/api/health")
    assert resp.status_code == 200

    headers = resp.headers
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    assert "Strict-Transport-Security" in headers
    assert "Content-Security-Policy" in headers
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_02_identifier_validation_and_sqli_rejection():
    """Identifier validator accepts safe IDs and strictly rejects SQLi / traversal attacks."""
    # Valid IDs
    assert is_valid_identifier("pay_RP_001_live") is True
    assert is_valid_identifier("mer_rzp_live_01") is True
    assert is_valid_identifier("cust_9988-abc") is True

    # Malicious injection payloads rejected
    malicious_inputs = [
        "pay_' OR '1'='1",
        "pay_; DROP TABLE payments;--",
        "pay_../../etc/passwd",
        "<script>alert('xss')</script>",
        "pay_\x00_nullbyte",
        "pay_123/*comment*/",
        "   ",
        "sh",  # Too short (< 4 chars)
        "a" * 70,  # Too long (> 64 chars)
    ]
    for bad_id in malicious_inputs:
        assert is_valid_identifier(bad_id) is False, f"Expected {bad_id} to be rejected"


def test_03_validate_id_api_endpoint():
    """POST /api/security/validate-id correctly parses good vs malicious IDs."""
    # Good ID
    res_good = client.post("/api/security/validate-id", json={"identifier": "pay_valid_12345", "expected_prefix": "pay"})
    assert res_good.status_code == 200
    assert res_good.json()["is_valid"] is True

    # Bad ID with SQLi
    res_bad = client.post("/api/security/validate-id", json={"identifier": "pay_1' OR 1=1--"})
    assert res_bad.status_code == 200
    assert res_bad.json()["is_valid"] is False

    # Prefix mismatch
    res_mismatch = client.post("/api/security/validate-id", json={"identifier": "mer_123456", "expected_prefix": "pay"})
    assert res_mismatch.status_code == 200
    assert res_mismatch.json()["is_valid"] is False


def test_04_secret_credential_masking():
    """Sanitizer masks sensitive credentials, tokens, and credit card numbers."""
    payload = {
        "user_email": "operator@store.com",
        "password": "SuperSecretPassword123!",
        "razorpay_key_secret": "rzp_secret_live_998877",
        "nested": {
            "api_key": "live_sk_abcdef123456",
            "card_number": "4111111111111234",
            "cvv": "999",
            "normal_field": "unmasked_value"
        }
    }
    sanitized = sanitize_payload(payload)

    # Sensitive fields are masked
    assert "SuperSecretPassword123!" not in str(sanitized)
    assert "rzp_secret_live_998877" not in str(sanitized)
    assert "live_sk_abcdef123456" not in str(sanitized)
    assert sanitized["password"] != "SuperSecretPassword123!"
    assert sanitized["nested"]["cvv"] == "******"
    # Non-sensitive field left intact
    assert sanitized["nested"]["normal_field"] == "unmasked_value"


def test_05_rate_limiting_sliding_window():
    """Sliding-window rate limiter permits burst up to cap and blocks excess."""
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=10)
    client_key = "test_client_ip_1"

    # First 3 allowed
    assert limiter.is_allowed(client_key) is True
    assert limiter.is_allowed(client_key) is True
    assert limiter.is_allowed(client_key) is True

    # 4th blocked
    assert limiter.is_allowed(client_key) is False

    # Reset allows again
    limiter.reset(client_key)
    assert limiter.is_allowed(client_key) is True


def test_06_execution_rate_limit_middleware_429():
    """Triggering excessive requests on sensitive endpoint returns HTTP 429."""
    # Temporarily set max_requests to 2 on execution_rate_limiter
    original_max = execution_rate_limiter.max_requests
    execution_rate_limiter.max_requests = 2
    execution_rate_limiter.reset()

    try:
        # First 2 requests succeed
        res1 = client.post("/api/execution/execute/pay_sec_001")
        res2 = client.post("/api/execution/execute/pay_sec_001")
        assert res1.status_code in (200, 400, 404, 422)
        assert res2.status_code in (200, 400, 404, 422)

        # 3rd request gets blocked by rate limiting middleware
        res3 = client.post("/api/execution/execute/pay_sec_001")
        assert res3.status_code == 429
        assert "Rate limit exceeded" in res3.json()["message"]
    finally:
        execution_rate_limiter.max_requests = original_max
        execution_rate_limiter.reset()


def test_07_payload_too_large_rejection_413():
    """Requests exceeding maximum content length return HTTP 413."""
    # Simulate oversized Content-Length header (> 2MB)
    headers = {"Content-Length": "3000000"}  # ~3MB
    resp = client.post("/api/security/validate-id", json={"identifier": "pay_test"}, headers=headers)
    assert resp.status_code == 413
    assert "PayloadTooLarge" in resp.json()["error"]


def test_08_get_security_audit_posture():
    """GET /api/security/audit returns hardened posture status."""
    resp = client.get("/api/security/audit")
    assert resp.status_code == 200
    data = resp.json()

    assert data["overall_status"] == "SECURE"
    assert len(data["checks"]) >= 5
    check_names = {c["name"] for c in data["checks"]}
    assert "Retry Limit Hard Ceiling" in check_names
    assert "Idempotency Lock Protection" in check_names
    assert "OWASP Security Headers" in check_names


def test_09_multi_tenant_isolation_cross_merchant_blocked():
    """Merchant A cannot execute recovery actions on Merchant B's payment."""
    app.dependency_overrides[get_current_user] = lambda: MERCHANT_A

    # pay_sec_002 belongs to Merchant B
    resp = client.post("/api/execution/execute/pay_sec_002")
    assert resp.status_code == 403
    assert "permission" in resp.json()["detail"].lower()


def test_10_retry_ceiling_guardrail_enforcement():
    """Verifies that the hard ceiling MAX_RETRY_LIMIT is strictly 3."""
    assert RecoveryExecutionService.MAX_RETRY_LIMIT == 3
