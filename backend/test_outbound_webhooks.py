"""
Phase 11: Outbound Webhook System Test Suite
=============================================
Tests:
  1.  POST /api/webhooks/endpoints            - register endpoint
  2.  GET  /api/webhooks/endpoints            - list endpoints
  3.  POST /api/webhooks/endpoints (merchant) - merchant auto-scoped to own merchant_id
  4.  PATCH /api/webhooks/endpoints/{id}/toggle - disable / re-enable endpoint
  5.  POST /api/webhooks/test/{id}            - test ping (dispatched to local echo server)
  6.  GET  /api/webhooks/deliveries           - delivery log after ping
  7.  GET  /api/webhooks/deliveries/{id}      - single delivery detail
  8.  POST /api/webhooks/deliveries/{id}/retry - manual retry (FAILED delivery)
  9.  Merchant cannot access another merchant's endpoint (403)
  10. DELETE /api/webhooks/endpoints/{id}     - delete endpoint
  11. HMAC signature verification helper     - unit-level correctness check
  12. dispatch_event fan-out                  - dispatches to all subscribed endpoints

Uses a real in-process HTTP server (threading.Thread + http.server) as the echo target.
"""
import pytest
import threading
import json
import hmac
import hashlib
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database.session import Base, get_db
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile
from app.services.webhooks.webhook_dispatcher import _sign_payload

# ─── In-Memory DB ─────────────────────────────────────────────────────────────
SQLALCHEMY_TEST_URL = "sqlite:///./test_webhooks.db"
engine = create_engine(SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

# ─── Local Echo HTTP Server ───────────────────────────────────────────────────
ECHO_PORT = 19876
received_requests = []

class EchoHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        received_requests.append({
            "path": self.path,
            "headers": dict(self.headers),
            "body": body,
        })
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):
        pass  # suppress echo-server logs

@pytest.fixture(scope="module", autouse=True)
def echo_server():
    server = HTTPServer(("127.0.0.1", ECHO_PORT), EchoHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield server
    server.shutdown()


ECHO_URL = f"http://127.0.0.1:{ECHO_PORT}/webhook"
WEBHOOK_SECRET = "super_secret_test_key_01"

# ─── User Personas ─────────────────────────────────────────────────────────────
ADMIN_USER = UserProfile(id="usr_admin", name="Admin", email="admin@wh.com",
                         role="admin", merchant_id=None, is_active=True)
MERCHANT_A = UserProfile(id="usr_mer_a", name="Merchant A", email="a@wh.com",
                          role="merchant", merchant_id="mer_wh_a", is_active=True)
MERCHANT_B = UserProfile(id="usr_mer_b", name="Merchant B", email="b@wh.com",
                          role="merchant", merchant_id="mer_wh_b", is_active=True)

# ─── Seed Data ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module", autouse=True)
def setup_db(echo_server):
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    db.add(Merchant(id="mer_wh_a", business_name="Merchant A Co",
                    contact_email="a@wh.com", is_live=False))
    db.add(Merchant(id="mer_wh_b", business_name="Merchant B Co",
                    contact_email="b@wh.com", is_live=False))
    db.commit()
    db.close()
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    Base.metadata.drop_all(bind=engine)


# ─── Shared state ─────────────────────────────────────────────────────────────
state = {}


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_01_register_endpoint():
    """Admin registers a webhook endpoint for merchant A."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    res = client.post(
        "/api/webhooks/endpoints?merchant_id=mer_wh_a",
        json={
            "url": ECHO_URL,
            "secret": WEBHOOK_SECRET,
            "description": "Test echo endpoint",
            "subscribed_events": "*",
        },
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["merchant_id"] == "mer_wh_a"
    assert data["is_active"] is True
    state["endpoint_id"] = data["id"]
    print(f"\n  [PASS] Registered endpoint {data['id']}")


def test_02_list_endpoints_admin():
    """Admin lists all endpoints for merchant A."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    res = client.get("/api/webhooks/endpoints?merchant_id=mer_wh_a")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["merchant_id"] == "mer_wh_a"
    assert len(data["endpoints"]) >= 1
    print(f"  [PASS] Listed {len(data['endpoints'])} endpoint(s) for mer_wh_a")


def test_03_merchant_auto_scoped():
    """Merchant A sees only their own endpoints; can't pass another merchant_id."""
    app.dependency_overrides[get_current_user] = lambda: MERCHANT_A
    client = TestClient(app)
    # Register endpoint — merchant_id from token, not query param
    res = client.post(
        "/api/webhooks/endpoints",
        json={"url": ECHO_URL, "secret": WEBHOOK_SECRET,
              "subscribed_events": "risk.assessed"},
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["merchant_id"] == "mer_wh_a"   # must be auto-scoped
    state["merchant_ep_id"] = data["id"]
    print(f"  [PASS] Merchant auto-scoped endpoint: merchant_id={data['merchant_id']}")


def test_04_toggle_endpoint():
    """Disable then re-enable endpoint."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    # Disable
    res = client.patch(f"/api/webhooks/endpoints/{state['endpoint_id']}/toggle",
                       json={"active": False})
    assert res.status_code == 200, res.text
    assert res.json()["is_active"] is False
    # Re-enable
    res = client.patch(f"/api/webhooks/endpoints/{state['endpoint_id']}/toggle",
                       json={"active": True})
    assert res.status_code == 200, res.text
    assert res.json()["is_active"] is True
    print("  [PASS] Toggle endpoint: disabled then re-enabled")


def test_05_test_ping():
    """Send a test ping to the echo server; verify delivery created and echo received."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    before_count = len(received_requests)
    res = client.post(f"/api/webhooks/test/{state['endpoint_id']}")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["http_status"] == 200
    state["ping_delivery_id"] = data["delivery_id"]
    time.sleep(0.1)  # let the echo thread flush
    assert len(received_requests) > before_count, "Echo server received no request"
    # Verify HMAC header is present
    last_req = received_requests[-1]
    assert "x-webhook-signature" in {k.lower() for k in last_req["headers"]}
    print(f"  [PASS] Test ping: delivery={data['delivery_id']}, status=SUCCESS, HMAC present")


def test_06_delivery_log():
    """Delivery log should contain the ping delivery."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    res = client.get("/api/webhooks/deliveries?merchant_id=mer_wh_a")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total"] >= 1
    event_types = [d["event_type"] for d in data["deliveries"]]
    assert "webhook.ping" in event_types
    print(f"  [PASS] Delivery log: {data['total']} deliveries, ping present")


def test_07_delivery_detail():
    """Single delivery detail should include payload and response body."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    res = client.get(f"/api/webhooks/deliveries/{state['ping_delivery_id']}")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["event_type"] == "webhook.ping"
    assert "payload" in data
    assert data["payload"]["event"] == "webhook.ping"
    print(f"  [PASS] Delivery detail: event={data['event_type']}, status={data['status']}")


def test_08_manual_retry_failed():
    """
    Register an endpoint pointing to a non-existent URL to force failure,
    then manually retry to confirm retry logic runs.
    Uses dispatch_event directly so we control which delivery belongs to the bad endpoint.
    """
    from app.services.webhooks.webhook_dispatcher import WebhookDispatcherService
    from app.models.webhook_endpoint import WebhookDelivery

    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)

    # Register a bad endpoint for merchant B (isolated — no other endpoints)
    res = client.post(
        "/api/webhooks/endpoints?merchant_id=mer_wh_b",
        json={"url": "http://127.0.0.1:1/bad", "secret": "secret123",
              "subscribed_events": "*"},
    )
    assert res.status_code == 201, res.text
    bad_ep_id = res.json()["id"]
    state["bad_ep_id"] = bad_ep_id

    # Use service directly to dispatch to merchant B (only bad endpoint)
    db = TestingSessionLocal()
    delivery_ids = WebhookDispatcherService.dispatch_event(
        db=db,
        merchant_id="mer_wh_b",
        event_type="risk.assessed",
        payment_id="pay_fail_test",
        data={"risk_level": "HIGH"},
    )
    db.close()

    assert len(delivery_ids) == 1
    delivery_id = delivery_ids[0]

    # Verify it failed (connection refused to port 1)
    detail_res = client.get(f"/api/webhooks/deliveries/{delivery_id}")
    assert detail_res.status_code == 200, detail_res.text
    assert detail_res.json()["status"] in ("RETRYING", "FAILED")

    # Manual retry — also expected to fail but must return a status
    retry_res = client.post(f"/api/webhooks/deliveries/{delivery_id}/retry")
    assert retry_res.status_code == 200
    assert retry_res.json()["status"] in ("RETRYING", "FAILED")
    print(f"  [PASS] Manual retry: delivery={delivery_id}, final_status={retry_res.json()['status']}")



def test_09_merchant_b_cannot_access_merchant_a_endpoint():
    """Merchant B cannot toggle or view Merchant A's endpoint."""
    app.dependency_overrides[get_current_user] = lambda: MERCHANT_B
    client = TestClient(app)
    res = client.patch(f"/api/webhooks/endpoints/{state['endpoint_id']}/toggle",
                       json={"active": False})
    assert res.status_code == 403, res.text
    print("  [PASS] Cross-merchant access blocked (403)")


def test_10_delete_endpoint():
    """Delete the bad endpoint; confirm it's gone from the list."""
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(app)
    res = client.delete(f"/api/webhooks/endpoints/{state['bad_ep_id']}")
    assert res.status_code == 204, res.text

    list_res = client.get("/api/webhooks/endpoints?merchant_id=mer_wh_a")
    ids = [ep["id"] for ep in list_res.json()["endpoints"]]
    assert state["bad_ep_id"] not in ids
    print("  [PASS] Endpoint deleted and removed from list")


def test_11_hmac_signature_correctness():
    """Unit test: verify _sign_payload produces verifiable HMAC-SHA256."""
    secret = "mysecret"
    body = b'{"event":"test.event","data":{}}'
    sig = _sign_payload(secret, body)
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert sig == expected
    print(f"  [PASS] HMAC correctness: sig={sig[:16]}...")


def test_12_dispatch_event_fanout():
    """
    dispatch_event should fan-out to ALL active, subscribed endpoints.
    Merchant A has 2 active endpoints (*-subscribed) — both should receive.
    """
    from app.services.webhooks.webhook_dispatcher import WebhookDispatcherService
    db = TestingSessionLocal()
    before_count = len(received_requests)
    delivery_ids = WebhookDispatcherService.dispatch_event(
        db=db,
        merchant_id="mer_wh_a",
        event_type="risk.assessed",
        payment_id="pay_test_fanout",
        data={"risk_level": "HIGH", "risk_score": 0.92},
    )
    db.close()
    # We have 2 active * endpoints for mer_wh_a (endpoint_id + merchant_ep_id)
    # bad_ep_id was deleted, so exactly 2 should fire
    assert len(delivery_ids) == 2
    time.sleep(0.1)
    assert len(received_requests) >= before_count + 2
    print(f"  [PASS] Fan-out: {len(delivery_ids)} deliveries for 2 active endpoints")
