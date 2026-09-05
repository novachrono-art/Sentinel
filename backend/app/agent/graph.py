from typing import Dict, Any, List
from langgraph.graph import StateGraph, START, END

from app.agent.state import RecoveryAgentState
from app.agent.nodes import (
    load_payment_node,
    risk_assessment_node,
    diagnose_node,
    recovery_decision_node,
    execute_recovery_node,
    verify_node,
    human_review_node,
    route_after_risk,
    route_after_decision,
    route_after_verify,
)

def build_recovery_graph():
    """
    Constructs and compiles the Stateful LangGraph Payment Recovery Agent.
    
    Graph Topology:
    START -> LOAD_PAYMENT -> RISK_ASSESSMENT -> [Conditional Edge: BENIGN vs RISKY_UNCERTAIN]
      - RISKY_UNCERTAIN -> HUMAN_REVIEW -> END
      - BENIGN -> DIAGNOSE -> RECOVERY_DECISION -> [Conditional Edge: EXECUTE vs ESCALATE]
          - ESCALATE -> HUMAN_REVIEW -> END
          - EXECUTE -> EXECUTE_RECOVERY -> VERIFY -> [Conditional Edge: SUCCESS vs RETRY vs ESCALATE]
              - SUCCESS -> END
              - RETRY (bounded by max_retries) -> RECOVERY_DECISION
              - ESCALATE -> HUMAN_REVIEW -> END
    """
    workflow = StateGraph(RecoveryAgentState)

    # 1. Register Nodes
    workflow.add_node("LOAD_PAYMENT", load_payment_node)
    workflow.add_node("RISK_ASSESSMENT", risk_assessment_node)
    workflow.add_node("DIAGNOSE", diagnose_node)
    workflow.add_node("RECOVERY_DECISION", recovery_decision_node)
    workflow.add_node("EXECUTE_RECOVERY", execute_recovery_node)
    workflow.add_node("VERIFY", verify_node)
    workflow.add_node("HUMAN_REVIEW", human_review_node)

    # 2. Add Fixed Ingestion Edges
    workflow.add_edge(START, "LOAD_PAYMENT")
    workflow.add_edge("LOAD_PAYMENT", "RISK_ASSESSMENT")

    # 3. Add Conditional Risk Branching Edge
    workflow.add_conditional_edges(
        "RISK_ASSESSMENT",
        route_after_risk,
        {
            "BENIGN": "DIAGNOSE",
            "RISKY_UNCERTAIN": "HUMAN_REVIEW"
        }
    )

    # 4. Diagnose to Decision Edge
    workflow.add_edge("DIAGNOSE", "RECOVERY_DECISION")

    # 5. Add Conditional Decision Edge (Guardrail check)
    workflow.add_conditional_edges(
        "RECOVERY_DECISION",
        route_after_decision,
        {
            "EXECUTE": "EXECUTE_RECOVERY",
            "ESCALATE": "HUMAN_REVIEW"
        }
    )

    # 6. Execute to Verification Edge
    workflow.add_edge("EXECUTE_RECOVERY", "VERIFY")

    # 7. Add Conditional Verification Edge (Bounded loop or termination)
    workflow.add_conditional_edges(
        "VERIFY",
        route_after_verify,
        {
            "SUCCESS": END,
            "RETRY": "RECOVERY_DECISION",
            "ESCALATE": "HUMAN_REVIEW"
        }
    )

    # 8. Human Review Terminal Edge
    workflow.add_edge("HUMAN_REVIEW", END)

    # Compile the graph
    app = workflow.compile()
    return app

# Singleton compiled graph instance
recovery_agent_graph = build_recovery_graph()

def get_graph_topology() -> Dict[str, Any]:
    """
    Returns visual schema representation of the state graph for frontend rendering.
    """
    return {
        "name": "Payment Recovery Stateful LangGraph",
        "version": "1.0.0",
        "nodes": [
            {"id": "START", "label": "Start Workflow", "type": "entry"},
            {"id": "LOAD_PAYMENT", "label": "Load Payment Context", "type": "fetch"},
            {"id": "RISK_ASSESSMENT", "label": "Deterministic Risk Classifier", "type": "classifier"},
            {"id": "DIAGNOSE", "label": "Failure Diagnosis Engine", "type": "analyzer"},
            {"id": "RECOVERY_DECISION", "label": "Recovery Decision Matrix", "type": "decision"},
            {"id": "EXECUTE_RECOVERY", "label": "Safe Action Execution", "type": "action"},
            {"id": "VERIFY", "label": "Outcome Verification", "type": "validator"},
            {"id": "HUMAN_REVIEW", "label": "Human-in-the-Loop Quarantine", "type": "escalation"},
            {"id": "END", "label": "Workflow Termination", "type": "exit"}
        ],
        "edges": [
            {"source": "START", "target": "LOAD_PAYMENT", "condition": None},
            {"source": "LOAD_PAYMENT", "target": "RISK_ASSESSMENT", "condition": None},
            {"source": "RISK_ASSESSMENT", "target": "DIAGNOSE", "condition": "Risk Score < 0.70 (BENIGN)"},
            {"source": "RISK_ASSESSMENT", "target": "HUMAN_REVIEW", "condition": "Risk Score >= 0.70 (RISKY/UNCERTAIN)"},
            {"source": "DIAGNOSE", "target": "RECOVERY_DECISION", "condition": None},
            {"source": "RECOVERY_DECISION", "target": "EXECUTE_RECOVERY", "condition": "Action Permitted (EXECUTE)"},
            {"source": "RECOVERY_DECISION", "target": "HUMAN_REVIEW", "condition": "Blocked / Escalated (ESCALATE)"},
            {"source": "EXECUTE_RECOVERY", "target": "VERIFY", "condition": None},
            {"source": "VERIFY", "target": "END", "condition": "Payment Recovered (SUCCESS)"},
            {"source": "VERIFY", "target": "RECOVERY_DECISION", "condition": "Retry count < Max Retries (RETRY)"},
            {"source": "VERIFY", "target": "HUMAN_REVIEW", "condition": "Max Retries Reached (ESCALATE)"},
            {"source": "HUMAN_REVIEW", "target": "END", "condition": "Quarantined & Awaiting Human Review"}
        ],
        "guardrails": [
            {"rule": "MAX_RETRY_ATTEMPTS = 3", "enforcement": "Deterministic boundary check in VERIFY and RECOVERY_DECISION"},
            {"rule": "HIGH_RISK_BLOCK", "enforcement": "Transactions with score >= 0.70 route immediately to HUMAN_REVIEW"},
            {"rule": "IMMUTABLE_AUDIT_TRAIL", "enforcement": "Every node logs state changes to audit_events"},
            {"rule": "IDEMPOTENCY_LOCK", "enforcement": "Each execution generates unique idempotency_key"}
        ]
    }
