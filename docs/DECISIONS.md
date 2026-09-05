# Architectural Decision Log (ADR)

## ADR-001: Technology Stack Selection
- **Status**: Accepted
- **Date**: 2026-08-27
- **Decision**: Use Python (FastAPI) for backend services and React (Vite) for frontend dashboard.
- **Why**: FastAPI provides asynchronous performance, native Pydantic validation, and seamless integration with ML models (scikit-learn) and orchestration frameworks (LangGraph). React + Vite delivers ultra-fast developer turnaround and component modularity.
- **Tradeoffs**: Dual-stack architecture requires managing Python and Node environments; however, this cleanly separates concerns between fintech state orchestration and responsive UI.

## ADR-002: Deterministic Risk Modeling Precedence
- **Status**: Accepted
- **Date**: 2026-08-27
- **Decision**: Risk evaluation must be performed by a deterministic ML/rule-based engine prior to any recovery action. LLMs cannot invent risk scores or override classification gates.
- **Why**: Financial compliance, safety, and auditability mandate reproducible and mathematically verifiable risk decisions.
- **Tradeoffs**: ML model requires explicit feature engineering and offline validation rather than zero-shot reasoning.

## ADR-003: LangGraph Orchestration & Bounded State Transitions
- **Status**: Accepted
- **Date**: 2026-08-27
- **Decision**: Orchestrate recovery workflows through a state graph with explicit node transitions and a hard ceiling of max 3 retry attempts before human escalation.
- **Why**: Prevents unbounded loops, infinite charge retries, and customer friction while maintaining full determinism.

## ADR-004: Neumorphic FinTech UI Design Language
- **Status**: Accepted
- **Date**: 2026-08-27
- **Decision**: Adopt a soft Neumorphic design system with extruded card elevations, inset input/press states, sleek fintech accents, and clear visual hierarchy.
- **Why**: Gives a tactile, modern, high-trust fintech feel while keeping data readable and actionable.

## ADR-005: Zero Hardcoded / Fabricated Metrics Policy
- **Status**: Accepted
- **Date**: 2026-08-27
- **Decision**: Every number, percentage, count, distribution chart, and conversion funnel in the UI must be dynamically computed directly from real state and active ingested records. Never display static fake or mock figures.
- **Why**: Financial compliance and trust require absolute mathematical fidelity. If no data exists, the UI must display honest zero / empty states (`₹0`, `0`, `0.0%`, `--`) rather than fabricated values.

## ADR-006: External Model Training in Google Colab & Lightweight Backend Inference
- **Status**: Accepted
- **Date**: 2026-08-30
- **Decision**: All machine learning model training, dataset synthesis, cross-validation, and hyperparameter tuning will be executed separately in Google Colab. The backend application will strictly load exported pre-trained model artifacts / weights (e.g. Joblib/ONNX/JSON) for real-time inference and feature extraction.
- **Why**: Decouples compute-heavy model training from the web service, speeds up server startup, avoids heavy GPU/training dependencies in production, and provides a clear workflow for data scientists to iterate in Colab notebooks.

## ADR-007: LangGraph State Machine Architecture & Bounded Retry Loops
- **Status**: Accepted
- **Date**: 2026-09-04
- **Decision**: Implement the core payment recovery cycle as a compiled LangGraph `StateGraph(RecoveryAgentState)`. The state graph enforces deterministic routing: `LOAD_PAYMENT` -> `RISK_ASSESSMENT` -> conditional branching (`BENIGN` -> `DIAGNOSE` -> `RECOVERY_DECISION` -> `EXECUTE_RECOVERY` -> `VERIFY`) vs (`RISKY_UNCERTAIN` -> `HUMAN_REVIEW`). Every state transition is recorded in `AgentRun` and `AuditEvent`.
- **Why**: Eliminates nondeterministic loops, provides complete step-by-step explainability, protects against rogue retries via a hard boundary (`max_retries = 3`), and decouples business logic into discrete testable nodes.
- **Tradeoffs**: Requires `langgraph` and `langchain-core` dependencies; however, it eliminates custom, error-prone state machines and offers standard graph introspection.

## ADR-008: Deterministic Policy Validation & Failure Taxonomy Classification
- **Status**: Accepted
- **Date**: 2026-09-04
- **Decision**: Standardize payment failures into 6 discrete taxonomy categories (`TEMPORARY_FAILURE`, `INSUFFICIENT_FUNDS`, `BANK_DECLINE`, `TIMEOUT`, `PAYMENT_METHOD_ISSUE`, `UNKNOWN`) via `DiagnosisService`. Decouple strategy recommendation from execution by routing all recovery action proposals through `RecoveryPolicyEngine` prior to execution.
- **Why**: Guarantees financial compliance and risk safety. While AI or heuristic layers recommend actions, the deterministic backend policy engine retains ultimate veto power to enforce hard retry ceilings (`max_retries = 3`), amount thresholds (downgrading direct charges > ₹50,000 to interactive links), risk boundaries (quarantining score >= 0.70), and idempotency.

## ADR-009: Razorpay Provider Abstraction & Credential Isolation
- **Status**: Accepted
- **Date**: 2026-09-04
- **Decision**: Implement gateway interaction via `PaymentProvider` abstraction with concrete `RazorpayProvider` and `DemoPaymentProvider`. Isolate all `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` credentials strictly on backend environment variables. Never expose raw API secrets in REST payloads, logs, or frontend responses. Implement automatic graceful sandbox simulation when mock keys are configured.
- **Why**: Prevents secret leaks, ensures PCI-DSS compliance, provides verifiable mock testing for CI/development without live credentials, and allows seamless switching between Test Mode and production environments.
