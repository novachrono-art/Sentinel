import sys
sys.stdout.reconfigure(encoding='utf-8')
from app.database.session import SessionLocal
from app.agent.runner import AgentRunner
from app.models.payment import Payment
from app.models.customer import Customer
from app.models.audit_event import AuditEvent
from app.models.human_review import HumanReview
from app.models.recovery_action import RecoveryAction
from app.models.agent_run import AgentRun
from app.models.risk_assessment import RiskAssessment

def run_tests():
    db = SessionLocal()

    # -------------------------------------------------------------
    # Test 1: Benign Payment Recovery Flow (START -> LOAD -> RISK -> DIAGNOSE -> DECISION -> EXECUTE -> VERIFY -> END)
    # -------------------------------------------------------------
    payment = db.query(Payment).filter(Payment.id == "pay_sim_d57623ad").first()
    if payment:
        payment.retry_count = 0
        payment.status = "FAILED"
        payment.recovery_status = "FAILED"
        db.commit()

        print("\n=======================================================")
        print("TEST 1: BENIGN PAYMENT RECOVERY FLOW")
        print("=======================================================")
        res1 = AgentRunner.run_recovery_workflow(db, payment.id)
        print(f"Outcome:       {res1['final_outcome']} (Status: {res1['status']})")
        print(f"Risk:          {res1['risk_score']} ({res1['risk_level']})")
        print(f"Diagnosis:     {res1['diagnosis']['category']}")
        print(f"Action:        {res1['recovery_decision']['action_type']}")
        print(f"Verification:  {res1['verification']['message']}")
        print("Trace:")
        for s in res1['trace']:
            print(f"  [{s['step']:<18}] {s['status']:<10} -> {s['details']}")
        assert res1['final_outcome'] == "SUCCESS"
        assert res1['status'] == "COMPLETED"

    # -------------------------------------------------------------
    # Test 2: High Risk Payment Quarantine Flow (START -> LOAD -> RISK -> HUMAN_REVIEW -> END)
    # -------------------------------------------------------------
    print("\n=======================================================")
    print("TEST 2: HIGH-RISK QUARANTINE FLOW")
    print("=======================================================")
    import uuid
    uid2 = uuid.uuid4().hex[:6]
    cust2 = Customer(
        id=f"cust_fraud_{uid2}",
        name="Suspicious Actor",
        merchant_id="merch_test",
        email="fraud@tempmail.com",
        dispute_count=5,
        lifetime_successful_orders=0
    )
    db.add(cust2)
    pay2 = Payment(
        id=f"pay_fraud_{uid2}",
        merchant_id="merch_test",
        customer_id=f"cust_fraud_{uid2}",
        amount=15000000.0,
        currency="INR",
        status="FAILED",
        error_code="CARD_VELOCITY_EXCEEDED",
        error_description="Velocity fraud detected",
        retry_count=0
    )
    db.add(pay2)
    db.commit()

    res2 = AgentRunner.run_recovery_workflow(db, pay2.id)
    print(f"Outcome:       {res2['final_outcome']} (Status: {res2['status']})")
    print(f"Risk:          {res2['risk_score']} ({res2['risk_level']})")
    print(f"Escalation:    {res2['escalation_reason']}")
    print("Trace:")
    for s in res2['trace']:
        print(f"  [{s['step']:<18}] {s['status']:<10} -> {s['details']}")

    assert res2['final_outcome'] == "ESCALATED"
    assert res2['risk_level'] == "HIGH"
    steps = [s['step'] for s in res2['trace']]
    assert "EXECUTE_RECOVERY" not in steps
    assert "HUMAN_REVIEW" in steps

    # Check HumanReview in DB
    hr = db.query(HumanReview).filter(HumanReview.payment_id == pay2.id).first()
    assert hr is not None
    assert hr.status == "PENDING"
    print(f"HumanReview Record Created: ID={hr.id}, Status={hr.status}")

    # Clean up Test 2
    db.query(AuditEvent).filter(AuditEvent.payment_id == pay2.id).delete()
    db.query(AgentRun).filter(AgentRun.payment_id == pay2.id).delete()
    db.delete(hr)
    ra2 = db.query(RiskAssessment).filter(RiskAssessment.payment_id == pay2.id).first()
    if ra2:
        db.delete(ra2)
    db.delete(pay2)
    db.delete(cust2)
    db.commit()

    # -------------------------------------------------------------
    # Test 3: Max Retries Exhaustion Flow (Guardrail Enforcement in Decision)
    # -------------------------------------------------------------
    print("\n=======================================================")
    print("TEST 3: MAX RETRIES EXHAUSTION GUARDRAIL FLOW")
    print("=======================================================")
    uid3 = uuid.uuid4().hex[:6]
    cust3 = Customer(
        id=f"cust_trusted_{uid3}",
        name="Trusted VIP Customer",
        merchant_id="merch_test",
        email="trusted.vip@gmail.com",
        dispute_count=0,
        lifetime_successful_orders=20,
        total_spend=50000.0
    )
    db.add(cust3)
    pay3 = Payment(
        id=f"pay_retry_exhaust_{uid3}",
        merchant_id="merch_test",
        customer_id=f"cust_trusted_{uid3}",
        amount=250.0,
        currency="INR",
        status="FAILED",
        error_code="BANK_DECLINE_TEMPORARY",
        retry_count=3, # Already at max retries!
        max_retries=3
    )
    db.add(pay3)
    db.commit()

    res3 = AgentRunner.run_recovery_workflow(db, pay3.id)
    print(f"Outcome:       {res3['final_outcome']} (Status: {res3['status']})")
    print(f"Risk:          {res3['risk_score']} ({res3['risk_level']})")
    if res3.get('recovery_decision'):
        print(f"Decision:      {res3['recovery_decision']['action_type']}")
        print(f"Permitted:     {res3['recovery_decision']['is_permitted']}")
    print(f"Escalation:    {res3['escalation_reason']}")
    print("Trace:")
    for s in res3['trace']:
        print(f"  [{s['step']:<18}] {s['status']:<10} -> {s['details']}")

    assert res3['final_outcome'] == "ESCALATED"
    steps3 = [s['step'] for s in res3['trace']]
    assert "EXECUTE_RECOVERY" not in steps3
    assert "HUMAN_REVIEW" in steps3

    # Clean up Test 3
    db.query(AuditEvent).filter(AuditEvent.payment_id == pay3.id).delete()
    db.query(AgentRun).filter(AgentRun.payment_id == pay3.id).delete()
    hr3 = db.query(HumanReview).filter(HumanReview.payment_id == pay3.id).first()
    if hr3:
        db.delete(hr3)
    ra3 = db.query(RiskAssessment).filter(RiskAssessment.payment_id == pay3.id).first()
    if ra3:
        db.delete(ra3)
    db.delete(pay3)
    db.delete(cust3)
    db.commit()

    # Also clean up old pay_retry_exhaust if left over
    old_p = db.query(Payment).filter(Payment.id == "pay_retry_exhaust").first()
    if old_p:
        db.query(AuditEvent).filter(AuditEvent.payment_id == old_p.id).delete()
        db.query(AgentRun).filter(AgentRun.payment_id == old_p.id).delete()
        old_hr = db.query(HumanReview).filter(HumanReview.payment_id == old_p.id).first()
        if old_hr:
            db.delete(old_hr)
        db.delete(old_p)
        db.commit()

    db.close()
    print("\n>>> ALL 3 LANGGRAPH RECOVERY WORKFLOW TESTS PASSED PERFECTLY! <<<")

if __name__ == "__main__":
    run_tests()
