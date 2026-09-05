# Open Questions & Design Considerations

## 1. Risk Model Training Data
- **Question**: Should initial feature sets be trained on synthetic merchant failure distributions, or should we provide an offline pre-trained logistic regression weight set alongside rule heuristics?
- **Current Approach**: Provide a rule + logistic regression hybrid engine with pre-calibrated feature weights, evaluateable on synthetic held-out validation datasets.

## 2. Notification Delivery Simulation
- **Question**: When a recovery decision is `CREATE_PAYMENT_LINK` or `SEND_REMINDER`, should we dispatch simulated webhooks / SMS / WhatsApp logs or connect to Twilio/SendGrid?
- **Current Approach**: In-app simulated delivery provider with mock notification events recorded in the audit trail.
