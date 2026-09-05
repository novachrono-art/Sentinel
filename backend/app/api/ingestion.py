from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from app.database.session import get_db
from app.services.ingestion.ingestion_service import IngestionService
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

router = APIRouter(prefix="/ingestion", tags=["Ingestion Simulator"])

class SimulateFailureRequest(BaseModel):
    scenario: str # "BANK_DECLINE_TEMPORARY" | "CARD_VELOCITY_EXCEEDED" | "MANDATE_EXHAUSTED" | "UPI_GATEWAY_TIMEOUT" | "CARD_EXPIRED"

@router.post("/simulate-failure")
def simulate_failure(
    payload: SimulateFailureRequest,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    valid_scenarios = [
        "BANK_DECLINE_TEMPORARY",
        "CARD_VELOCITY_EXCEEDED",
        "MANDATE_EXHAUSTED",
        "UPI_GATEWAY_TIMEOUT",
        "CARD_EXPIRED"
    ]
    if payload.scenario not in valid_scenarios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scenario '{payload.scenario}'. Valid options: {valid_scenarios}"
        )

    payment = IngestionService.simulate_failure_scenario(db, payload.scenario)
    return {
        "status": "success",
        "message": f"Successfully simulated and ingested scenario: {payload.scenario}",
        "payment_id": payment.id,
        "amount": payment.amount,
        "failure_reason": payment.failure_reason,
        "risk_level": payment.risk_assessment.risk_level if payment.risk_assessment else "LOW",
        "recovery_status": payment.recovery_status
    }

@router.post("/seed-batch")
def seed_demo_batch(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    scenarios = [
        "BANK_DECLINE_TEMPORARY",
        "CARD_VELOCITY_EXCEEDED",
        "MANDATE_EXHAUSTED",
        "UPI_GATEWAY_TIMEOUT",
        "CARD_EXPIRED"
    ]
    ingested = []
    for sc in scenarios:
        p = IngestionService.simulate_failure_scenario(db, sc)
        ingested.append({"id": p.id, "scenario": sc, "amount": p.amount})

    return {
        "status": "success",
        "message": f"Successfully ingested batch of {len(ingested)} failure events.",
        "items": ingested
    }

@router.delete("/clear")
def clear_all_payments(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    IngestionService.clear_all_payments(db)
    return {
        "status": "success",
        "message": "All payment and audit event records cleared. Feed reset to zero state."
    }
