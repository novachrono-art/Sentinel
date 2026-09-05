export const MOCK_FAILED_PAYMENTS = [
  {
    id: 'pay_RP_DEMO_001',
    customerName: 'Rahul Sharma',
    customerEmail: 'rahul.sharma@example.com',
    amount: 4999,
    currency: 'INR',
    failureReason: 'Temporary bank decline (Insufficient balance response from issuing bank)',
    failureCode: 'BANK_DECLINE_TEMPORARY',
    riskLevel: 'LOW',
    riskScore: 0.18,
    recoveryStatus: 'RECOVERED',
    retryCount: 1,
    maxRetries: 3,
    timestamp: '2026-08-27 18:42:10',
    historyCount: 3,
    recommendedAction: 'Retry after 24h',
    aiDiagnosis: 'Customer has 3 prior successful payments with no dispute history. Issuing bank experienced high failure rates in this settlement window. Safe to execute automated retry.',
    signals: [
      '3 Successful Past Transactions',
      'Consistent IP / Device Fingerprint',
      'Zero Chargeback / Fraud Flags'
    ]
  },
  {
    id: 'pay_RP_DEMO_002',
    customerName: 'Aarav Mehta',
    customerEmail: 'aarav.m99@unknown-domain.io',
    amount: 35000,
    currency: 'INR',
    failureReason: 'Velocity threshold exceeded & anomalous card origin',
    failureCode: 'CARD_VELOCITY_EXCEEDED',
    riskLevel: 'HIGH',
    riskScore: 0.84,
    recoveryStatus: 'IN_REVIEW',
    retryCount: 0,
    maxRetries: 3,
    timestamp: '2026-08-27 19:15:32',
    historyCount: 0,
    recommendedAction: 'Quarantine & Escalate to Human Reviewer',
    aiDiagnosis: 'Unusually large transaction amount with zero account tenure. Rapid succession of card attempts across different geographic regions. Automated recovery blocked by deterministic safety gate.',
    signals: [
      'High-Value Anomaly (₹35,000)',
      'New Customer / 0 Prior Purchases',
      'Velocity Spike: 4 attempts in 3 mins',
      'Disposable Email Domain'
    ]
  },
  {
    id: 'pay_RP_DEMO_003',
    customerName: 'Pooja Verma',
    customerEmail: 'pooja.verma@techcorp.in',
    amount: 8500,
    currency: 'INR',
    failureReason: 'Mandate execution failure / Max retries exhausted',
    failureCode: 'MANDATE_EXHAUSTED',
    riskLevel: 'MEDIUM',
    riskScore: 0.45,
    recoveryStatus: 'HELD',
    retryCount: 3,
    maxRetries: 3,
    timestamp: '2026-08-27 14:02:19',
    historyCount: 1,
    recommendedAction: 'Issue Payment Link via SMS/Email',
    aiDiagnosis: 'System attempted 3 automated retries across 48 hours without authorization. Safety guardrail capped further automated attempts. Requires interactive customer payment link or merchant manual contact.',
    signals: [
      'Retry Limit (3/3) Reached',
      'Recurring Subscription Mandate Failed',
      'Requires Customer Re-authentication'
    ]
  },
  {
    id: 'pay_RP_DEMO_004',
    customerName: 'Vikram Malhotra',
    customerEmail: 'vikram.m@zenith.org',
    amount: 12400,
    currency: 'INR',
    failureReason: 'Payment Gateway Timeout on UPI Intent',
    failureCode: 'UPI_GATEWAY_TIMEOUT',
    riskLevel: 'LOW',
    riskScore: 0.22,
    recoveryStatus: 'RETRYING',
    retryCount: 1,
    maxRetries: 3,
    timestamp: '2026-08-27 20:30:14',
    historyCount: 5,
    recommendedAction: 'Verify NPCI status & auto-retry',
    aiDiagnosis: 'NPCI UPI switch experienced temporary network timeout during intent resolution. High customer lifetime value with 5 prior settlements. Background verification scheduled.',
    signals: [
      'Known UPI Gateway Switch Degradation',
      '5 Previous Successful Settlements',
      'No Risk Flags Detected'
    ]
  },
  {
    id: 'pay_RP_DEMO_005',
    customerName: 'Sneha Patel',
    customerEmail: 'sneha.patel@designstudio.co',
    amount: 18900,
    currency: 'INR',
    failureReason: 'Expired Card Details',
    failureCode: 'CARD_EXPIRED',
    riskLevel: 'LOW',
    riskScore: 0.15,
    recoveryStatus: 'SCHEDULED',
    retryCount: 0,
    maxRetries: 3,
    timestamp: '2026-08-27 21:10:45',
    historyCount: 2,
    recommendedAction: 'Dispatch Smart Payment Link with Card Update',
    aiDiagnosis: 'Card expired at the end of the previous month. Automated silent retry will fail; smart email/WhatsApp recovery link generated with auto-filled checkout token.',
    signals: [
      'Card Expiry Date Reached',
      'Low Risk / Verified Merchant Customer'
    ]
  }
];

export const MOCK_AUDIT_LOGS = [
  {
    id: 'aud_001',
    timestamp: '2026-08-27 18:42:11',
    paymentId: 'pay_RP_DEMO_001',
    event: 'FAILURE_INGESTED',
    actor: 'Razorpay Provider Adapter',
    details: 'Received failed webhook payload for ₹4,999. Failure reason: Temporary bank decline.',
    riskLevel: 'LOW',
    outcome: 'PROCESSED'
  },
  {
    id: 'aud_002',
    timestamp: '2026-08-27 18:42:12',
    paymentId: 'pay_RP_DEMO_001',
    event: 'RISK_EVALUATION',
    actor: 'Deterministic Risk Classifier v1',
    details: 'Extracted 8 features. Computed risk score 0.18 (LOW). Passed safety gate threshold < 0.35.',
    riskLevel: 'LOW',
    outcome: 'PASSED'
  },
  {
    id: 'aud_003',
    timestamp: '2026-08-27 18:42:14',
    paymentId: 'pay_RP_DEMO_001',
    event: 'AI_DIAGNOSIS',
    actor: 'LangGraph Reasoning Agent',
    details: 'Diagnosed transient issuing bank latency. Selected action: RETRY (Attempt 1/3).',
    riskLevel: 'LOW',
    outcome: 'ACTION_SELECTED'
  },
  {
    id: 'aud_004',
    timestamp: '2026-08-27 18:42:15',
    paymentId: 'pay_RP_DEMO_001',
    event: 'RECOVERY_EXECUTED',
    actor: 'Razorpay Provider Adapter',
    details: 'Dispatched idempotent payment retry token rzp_retry_001a9. Result: SUCCESS 200 OK.',
    riskLevel: 'LOW',
    outcome: 'RECOVERED'
  },
  {
    id: 'aud_005',
    timestamp: '2026-08-27 19:15:33',
    paymentId: 'pay_RP_DEMO_002',
    event: 'SAFETY_GATE_TRIGGERED',
    actor: 'Deterministic Risk Classifier v1',
    details: 'Calculated risk score 0.84 (HIGH). Multiple anomalous signals detected. Automatic recovery BLOCKED.',
    riskLevel: 'HIGH',
    outcome: 'QUARANTINED'
  },
  {
    id: 'aud_006',
    timestamp: '2026-08-27 19:15:34',
    paymentId: 'pay_RP_DEMO_002',
    event: 'HUMAN_REVIEW_ESCALATION',
    actor: 'LangGraph State Machine',
    details: 'Payment escalated to Human Review Queue. Notification dispatched to operations team.',
    riskLevel: 'HIGH',
    outcome: 'IN_REVIEW'
  }
];
