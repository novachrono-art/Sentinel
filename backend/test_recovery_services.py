import sys
sys.stdout.reconfigure(encoding='utf-8')

from app.database.session import SessionLocal
from app.database.init_db import init_db
from app.models.payment import Payment
from app.services.recovery.diagnosis_service import DiagnosisService
from app.services.recovery.recovery_decision_service import RecoveryDecisionService
from app.services.recovery.policy import RecoveryPolicyEngine
from fastapi.testclient import TestClient
from app.main import app
from app.utils.auth import create_access_token
import pytest

# Fixture to initialize the database tables before each test
@pytest.fixture(scope="function")
def db():
    init_db()
    db = SessionLocal()
    yield db
    db.close()

# Fixture to create a sample payment record used in API tests
@pytest.fixture(scope="function")
def sample_payment(db):
    payment = Payment(
        id="pay_sim_d57623ad",
        merchant_id="merch_1",
        customer_id="cust_1",
        amount=1000.0,
        currency="INR",
        status="FAILED",
        error_code="BANK_DECLINE_TEMPORARY",
        retry_count=0,
        max_retries=3,
    )
    # Remove any existing payment with same ID to avoid IntegrityError
    existing = db.query(Payment).filter(Payment.id == payment.id).first()
    if existing:
        db.delete(existing)
        db.commit()
    db.add(payment)
    db.commit()
    db.refresh(payment)
    yield payment
    # Cleanup after test
    db.delete(payment)
    db.commit()

def test_failure_taxonomy_classification():
    print("\n--- 1. Testing Failure Situations Classification ---")
    scenarios = [
        ("BANK_DECLINE_TEMPORARY", "TEMPORARY_FAILURE", "RETRY"),
        ("GATEWAY_TIMEOUT", "TIMEOUT", "RETRY"),
        ("INSUFFICIENT_FUNDS", "INSUFFICIENT_FUNDS", "CREATE_PAYMENT_LINK"),
        ("CARD_EXPIRED", "PAYMENT_METHOD_ISSUE", "CREATE_PAYMENT_LINK"),
        ("AUTHENTICATION_FAILED", "PAYMENT_METHOD_ISSUE", "CREATE_PAYMENT_LINK"),
        ("BANK_DECLINE", "BANK_DECLINE", "RETRY"),
        ("RANDOM_CUSTOM_ERR_999", "UNKNOWN", "CREATE_PAYMENT_LINK"),
    ]

    for err_code, expected_cat, expected_action in scenarios:
        p = Payment(
            id="test_diag",
            merchant_id="merch_1",
            customer_id="cust_1",
            amount=1000.0,
            currency="INR",
            status="FAILED",
            error_code=err_code,
            retry_count=0
        )
        diag = DiagnosisService.diagnose(p)
        print(f"  [{err_code:<25}] -> Category: {diag.category:<22} Action: {diag.recommended_action:<20} Conf: {diag.confidence:.0%}")
        assert diag.category == expected_cat, f"Expected {expected_cat}, got {diag.category}"
        assert diag.recommended_action == expected_action, f"Expected {expected_action}, got {diag.recommended_action}"
    print("All 6 failure categories successfully classified!")

def test_deterministic_policy_guardrails():
    print("\n--- 2. Testing Deterministic Policy Guardrails ---")
    
    # Test Guardrail A: High Risk Blocks Direct Action
    res_risk = RecoveryPolicyEngine.evaluate(
        recommended_action="RETRY",
        failure_category="TEMPORARY_FAILURE",
        risk_score=0.88,
        risk_level="HIGH",
        retry_count=0,
        max_retries=3,
        amount=500.0,
        payment_status="FAILED"
    )
    print(f"  High Risk (0.88): Permitted={res_risk.is_permitted}, Action={res_risk.final_action}, Reason={res_risk.reason}")
    assert res_risk.is_permitted is False
    assert res_risk.final_action == "ESCALATE"

    # Test Guardrail B: Max Retries Exceeded
    res_max = RecoveryPolicyEngine.evaluate(
        recommended_action="RETRY",
        failure_category="TEMPORARY_FAILURE",
        risk_score=0.10,
        risk_level="LOW",
        retry_count=3,
        max_retries=3,
        amount=500.0,
        payment_status="FAILED"
    )
    print(f"  Max Retries (3/3): Permitted={res_max.is_permitted}, Action={res_max.final_action}, Reason={res_max.reason}")
    assert res_max.is_permitted is False
    assert res_max.final_action == "ESCALATE"

    # Test Guardrail C: High Amount Direct Retry Downgrade to Link
    res_amt = RecoveryPolicyEngine.evaluate(
        recommended_action="RETRY",
        failure_category="TEMPORARY_FAILURE",
        risk_score=0.10,
        risk_level="LOW",
        retry_count=0,
        max_retries=3,
        amount=150000.0, # ₹1,50,000 exceeds ₹50,000 threshold
        payment_status="FAILED"
    )
    print(f"  Large Amount (₹1.5L): Permitted={res_amt.is_permitted}, Action={res_amt.final_action}, Reason={res_amt.reason}")
    assert res_amt.is_permitted is True
    assert res_amt.final_action == "CREATE_PAYMENT_LINK"

    # Test Guardrail D: Already Settled / Captured Check
    res_settled = RecoveryPolicyEngine.evaluate(
        recommended_action="RETRY",
        failure_category="TEMPORARY_FAILURE",
        risk_score=0.10,
        risk_level="LOW",
        retry_count=0,
        max_retries=3,
        amount=500.0,
        payment_status="CAPTURED"
    )
    print(f"  Already Settled: Permitted={res_settled.is_permitted}, Action={res_settled.final_action}")
    assert res_settled.is_permitted is False
    assert res_settled.final_action == "WAIT"

    print("All deterministic policy guardrail checks verified!")

def test_api_endpoints(sample_payment):
    print("\n--- 3. Testing REST Endpoints for Diagnosis & Strategy ---")
    client = TestClient(app)
    token = create_access_token('merchant@razorpay-recovery.io', 'merchant')
    headers = {'Authorization': f'Bearer {token}'}

    # A. Taxonomy
    tax_res = client.get('/api/recovery/taxonomy', headers=headers)
    assert tax_res.status_code == 200
    tax_data = tax_res.json()
    print(f"  Taxonomy API: {len(tax_data['categories'])} categories, {len(tax_data['recovery_actions'])} actions")

    # B. Policy Rules
    pol_res = client.get('/api/recovery/policy-rules', headers=headers)
    assert pol_res.status_code == 200
    pol_data = pol_res.json()
    print(f"  Policy Rules API: {len(pol_data['rules'])} guardrails registered")

    # C. Diagnose payment
    diag_res = client.post('/api/recovery/diagnose/pay_sim_d57623ad', headers=headers)
    assert diag_res.status_code == 200
    diag_payload = diag_res.json()['diagnosis']
    print(f"  Diagnose Endpoint: Category=[{diag_payload['category']}], Action=[{diag_payload['recommended_action']}]")
    print(f"    Customer Msg: {diag_payload['customer_message']}")

    # D. Decision payment
    dec_res = client.post('/api/recovery/decision/pay_sim_d57623ad', headers=headers)
    assert dec_res.status_code == 200
    dec_payload = dec_res.json()['decision']
    print(f"  Decision Endpoint: Action=[{dec_payload['action_type']}], Channel=[{dec_payload['channel']}], Permitted={dec_payload['is_permitted']}")

    print("All Phase 8 REST endpoints working with 200 OK!")

if __name__ == "__main__":
    test_failure_taxonomy_classification()
    test_deterministic_policy_guardrails()
    test_api_endpoints()
    print("\n>>> ALL PHASE 8 VALIDATION TESTS PASSED CLEANLY! <<<")
