import uuid
import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.agent.graph import recovery_agent_graph
from app.agent.state import RecoveryAgentState
from app.models.agent_run import AgentRun
from app.models.payment import Payment
from app.utils.logger import logger

class AgentRunner:
    """
    Service to execute the LangGraph Payment Recovery Workflow,
    persisting state snapshots into AgentRun and managing transactions.
    """

    @classmethod
    def run_recovery_workflow(cls, db: Session, payment_id: str) -> Dict[str, Any]:
        """
        Executes the stateful recovery workflow for a specific failed payment.
        """
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        logger.info(f"Initiating LangGraph recovery workflow {run_id} for payment {payment_id}")

        # 1. Fetch payment to verify initial state
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            raise ValueError(f"Payment with ID '{payment_id}' does not exist.")

        # 2. Build initial state
        initial_state: RecoveryAgentState = {
            "run_id": run_id,
            "payment_id": payment.id,
            "merchant_id": payment.merchant_id,
            "customer_id": payment.customer_id,
            "retry_count": payment.retry_count or 0,
            "max_retries": payment.max_retries or 3,
            "trace": [],
            "current_step": "START"
        }

        # 3. Create AgentRun record in database
        agent_run = AgentRun(
            id=run_id,
            payment_id=payment.id,
            initial_state={
                "payment_id": payment.id,
                "amount": payment.amount,
                "currency": payment.currency,
                "status": payment.status,
                "error_code": payment.error_code,
                "retry_count": payment.retry_count
            },
            status="RUNNING",
            started_at=datetime.datetime.utcnow()
        )
        db.add(agent_run)
        db.commit()

        # 4. Invoke LangGraph with DB context
        try:
            config = {
                "configurable": {
                    "db": db
                },
                "recursion_limit": 15 # Bounded recursion protection
            }
            
            final_state = recovery_agent_graph.invoke(initial_state, config=config)

            # Determine final status
            outcome = final_state.get("final_outcome", "FAILED")
            if outcome == "SUCCESS":
                run_status = "COMPLETED"
            elif outcome in ["ESCALATE", "ESCALATED"]:
                run_status = "ESCALATED"
            else:
                run_status = "FAILED"

            # 5. Update AgentRun record
            agent_run.final_state = {
                "final_outcome": final_state.get("final_outcome"),
                "risk_score": final_state.get("risk_score"),
                "risk_level": final_state.get("risk_level"),
                "diagnosis": final_state.get("diagnosis"),
                "recovery_decision": final_state.get("recovery_decision"),
                "recovery_attempt": final_state.get("recovery_attempt"),
                "verification": final_state.get("verification"),
                "retry_count": final_state.get("retry_count"),
                "escalation_reason": final_state.get("escalation_reason"),
                "trace_steps_count": len(final_state.get("trace", []))
            }
            agent_run.status = run_status
            agent_run.completed_at = datetime.datetime.utcnow()
            db.commit()

            logger.info(f"LangGraph recovery workflow {run_id} finished: Outcome={outcome}, Status={run_status}")

            return {
                "run_id": run_id,
                "payment_id": payment_id,
                "status": run_status,
                "final_outcome": final_state.get("final_outcome"),
                "risk_score": final_state.get("risk_score"),
                "risk_level": final_state.get("risk_level"),
                "diagnosis": final_state.get("diagnosis"),
                "recovery_decision": final_state.get("recovery_decision"),
                "recovery_attempt": final_state.get("recovery_attempt"),
                "verification": final_state.get("verification"),
                "retry_count": final_state.get("retry_count"),
                "escalation_reason": final_state.get("escalation_reason"),
                "trace": final_state.get("trace", [])
            }

        except Exception as e:
            logger.exception(f"LangGraph execution error for {payment_id}: {e}")
            agent_run.status = "FAILED"
            agent_run.final_state = {"error": str(e)}
            agent_run.completed_at = datetime.datetime.utcnow()
            db.commit()
            raise e
