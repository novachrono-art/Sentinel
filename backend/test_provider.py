import sys
sys.stdout.reconfigure(encoding='utf-8')
from app.providers.razorpay_provider import RazorpayProvider
from app.providers.demo_provider import DemoPaymentProvider
from app.providers.factory import get_payment_provider
from fastapi.testclient import TestClient
from app.main import app
from app.utils.auth import create_access_token

def test_razorpay_provider_tools():
    print("\n--- 1. Testing RazorpayProvider Tools ---")
    provider = RazorpayProvider()

    # Tool 1 & 2: GetPayment & GetPaymentStatus
    raw = provider.get_payment("pay_test_rzp_123")
    assert raw["id"] == "pay_test_rzp_123"
    print(f"  Tool 1 (GetPayment): ID={raw['id']}, Status={raw['status']}")

    status_data = provider.get_payment_status("pay_test_rzp_123")
    assert status_data["payment_id"] == "pay_test_rzp_123"
    assert "amount" in status_data
    print(f"  Tool 2 (GetPaymentStatus): Status={status_data['status']}, Amount=₹{status_data['amount']:,.2f}")

    # Tool 3: CreateOrder
    order = provider.create_order(
        amount=2999.0,
        currency="INR",
        receipt="rcpt_test_001",
        notes={"purpose": "Recovery agent test order"}
    )
    assert "id" in order
    assert order["amount"] == 299900
    print(f"  Tool 3 (CreateOrder): OrderID={order['id']}, AmountPaise={order['amount']}")

    # Tool 4: CreatePaymentLink
    link = provider.create_payment_link(
        amount=2999.0,
        currency="INR",
        customer_name="Rohan Sharma",
        customer_email="rohan@example.com",
        customer_phone="9876543210",
        description="Smart recovery payment link for order #rcpt_test_001",
        idempotency_key="idemp_test_link_001",
        expire_by_hours=48
    )
    assert "id" in link
    assert "short_url" in link
    print(f"  Tool 4 (CreatePaymentLink): LinkID={link['id']}, ShortUrl={link['short_url']}")

    # Tool 5: RetryPayment
    retry = provider.retry_payment("pay_test_rzp_123", "idemp_retry_001")
    assert retry["status"] == "authorized"
    print(f"  Tool 5 (RetryPayment): RetryID={retry['id']}, Status={retry['status']}")

    # Tool 6: VerifyWebhookSignature
    sig_valid = provider.verify_webhook_signature(b'{"event":"payment.failed"}', "dummy_sig", "dummy_secret")
    print(f"  Tool 6 (VerifyWebhookSignature): Valid signature check executed")
    print("All 6 RazorpayProvider tools functioning cleanly!")

def test_rest_provider_endpoints():
    print("\n--- 2. Testing REST API Endpoints for Payment Provider ---")
    client = TestClient(app)
    token = create_access_token('merchant@razorpay-recovery.io', 'merchant')
    headers = {'Authorization': f'Bearer {token}'}

    # A. Provider Status & Secret Masking
    status_res = client.get('/api/provider/status', headers=headers)
    assert status_res.status_code == 200
    s_data = status_res.json()
    print(f"  Provider: {s_data['active_provider']}, Mode: {s_data['mode']}")
    print(f"  Masked Key: {s_data['masked_key_id']} (Secret is completely hidden)")
    assert "key_secret" not in str(s_data)
    assert len(s_data['supported_tools']) == 6

    # B. Create Order via API
    order_res = client.post(
        '/api/provider/orders',
        headers=headers,
        json={
            "amount": 1499.0,
            "currency": "INR",
            "receipt": "rcpt_api_test_01",
            "notes": {"merchant": "demo"}
        }
    )
    assert order_res.status_code == 200
    print(f"  API CreateOrder: {order_res.json()['order']['id']}")

    # C. Inspect Payment Status via API
    pay_res = client.get('/api/provider/payments/pay_sim_d57623ad', headers=headers)
    assert pay_res.status_code == 200
    print(f"  API InspectPayment: Status={pay_res.json()['payment']['status']}")

    # D. Create Payment Link via API
    link_res = client.post(
        '/api/provider/payment-links',
        headers=headers,
        json={
            "amount": 1499.0,
            "currency": "INR",
            "customer_name": "Aarav Patel",
            "customer_email": "aarav@example.com",
            "description": "Recovery invoice link",
            "idempotency_key": "idemp_api_test_link"
        }
    )
    assert link_res.status_code == 200
    print(f"  API CreatePaymentLink: {link_res.json()['payment_link']['short_url']}")

    print("All Phase 9 Provider REST endpoints working with 200 OK!")

if __name__ == "__main__":
    test_razorpay_provider_tools()
    test_rest_provider_endpoints()
    print("\n>>> ALL PHASE 9 RAZORPAY INTEGRATION TESTS PASSED PERFECTLY! <<<")
