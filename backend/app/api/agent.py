from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from app.database.session import get_db
from app.models.agent_run import AgentRun
from app.models.payment import Payment
from app.agent.runner import AgentRunner
from app.agent.graph import get_graph_topology
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

router = APIRouter(prefix="/agent", tags=["Recovery Agent Workflow"])

@router.post("/recover/{payment_id}")
def trigger_payment_recovery(
    payment_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Executes the autonomous LangGraph payment recovery workflow on a failed payment.
    Enforces risk safety, failure diagnosis, recovery guardrails, and verification.
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment with ID '{payment_id}' was not found."
        )

    # If user is merchant, ensure they own the payment or it is within default demo merchant
    if current_user.role == "merchant" and current_user.merchant_id:
        if payment.merchant_id not in [current_user.merchant_id, "mer_rzp_default", "mer_test_01"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to trigger recovery for this merchant's payments."
            )

    try:
        result = AgentRunner.run_recovery_workflow(db, payment_id)
        return {
            "status": "success",
            "message": f"Recovery workflow finished with outcome: {result['final_outcome']}",
            "data": result
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Recovery agent workflow execution failed: {str(e)}"
        )

@router.get("/topology")
def get_workflow_topology(
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Returns the visual LangGraph workflow topology, node definitions, conditional edges, and safety guardrails.
    """
    return get_graph_topology()

@router.get("/runs/{run_id}")
def get_agent_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Retrieves execution state, parameters, and audit history for a specific AgentRun.
    """
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent run '{run_id}' not found."
        )

    return {
        "id": run.id,
        "payment_id": run.payment_id,
        "status": run.status,
        "initial_state": run.initial_state,
        "final_state": run.final_state,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None
    }

@router.get("/runs/payment/{payment_id}")
def get_runs_by_payment(
    payment_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Retrieves all recovery runs executed for a given payment.
    """
    runs = db.query(AgentRun).filter(AgentRun.payment_id == payment_id).order_by(AgentRun.started_at.desc()).all()
    return [
        {
            "id": r.id,
            "payment_id": r.payment_id,
            "status": r.status,
            "initial_state": r.initial_state,
            "final_state": r.final_state,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None
        }
        for r in runs
    ]
