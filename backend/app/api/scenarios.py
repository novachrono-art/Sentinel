"""
Phase 14: Critical Failure Scenarios REST API
=============================================
Endpoints:
  POST /api/scenarios/run-all            - Execute and verify all 6 critical scenarios
  POST /api/scenarios/{scenario_num}/run - Execute a specific scenario (1 to 6)
  GET  /api/scenarios/catalog            - Catalog of the 6 critical scenarios
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any

from app.database.session import get_db
from app.services.recovery.scenario_service import ScenarioVerificationService
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

router = APIRouter(prefix="/scenarios", tags=["Critical Failure Scenarios Verification"])

SCENARIO_CATALOG = [
    {
        "number": 1,
        "id": "scenario_1_successful_recovery",
        "name": "Successful Recovery",
        "chain": "Failed -> Low Risk -> Direct Gateway Retry -> Success (RECOVERED)",
        "guardrail": "Automatic execution permitted within safety boundaries"
    },
    {
        "number": 2,
        "id": "scenario_2_retry_required",
        "name": "Retry Required",
        "chain": "Failed -> Low Risk -> Retry #1 Failed -> Retry #2 Success (RECOVERED)",
        "guardrail": "Multi-attempt bounded retry with exponential backoff / state persistence"
    },
    {
        "number": 3,
        "id": "scenario_3_retry_limit",
        "name": "Retry Limit Enforcement",
        "chain": "Failed -> Retries Exhausted (3/3) -> STOP -> Auto-Quarantined",
        "guardrail": "Hard ceiling (MAX_RETRY_LIMIT = 3) halts automated charges"
    },
    {
        "number": 4,
        "id": "scenario_4_risky_payment",
        "name": "Risky Payment Guardrail",
        "chain": "Failed -> High Risk Score (0.92 >= 0.70) -> STOP -> Immediate Quarantine",
        "guardrail": "Zero Gateway Touch: Pre-flight check blocks high risk"
    },
    {
        "number": 5,
        "id": "scenario_5_unknown_state",
        "name": "Unknown / Ambiguous State",
        "chain": "Payment in PENDING_VERIFICATION -> STOP -> Fail-Closed & Human Review",
        "guardrail": "Fail-Closed: Ambiguous gateway state halts retries to prevent double charging"
    },
    {
        "number": 6,
        "id": "scenario_6_duplicate_action",
        "name": "Duplicate Action Idempotency Protection",
        "chain": "Same Idempotency Key Twice -> 2nd Action Blocked & Suppressed",
        "guardrail": "Idempotency Lock: Guarantees zero duplicate billing"
    }
]


@router.get("/catalog")
def get_scenario_catalog(
    current_user: UserProfile = Depends(get_current_user)
):
    """Returns the complete catalog and definitions of the 6 critical scenarios."""
    return {
        "total": len(SCENARIO_CATALOG),
        "scenarios": SCENARIO_CATALOG
    }


@router.post("/run-all")
def run_all_scenarios(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    """Executes all 6 critical scenarios and returns certification results."""
    return ScenarioVerificationService.run_all_scenarios(db=db)


@router.post("/{scenario_num}/run")
def run_single_scenario(
    scenario_num: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    """Executes a single specified scenario (1 to 6)."""
    if scenario_num == 1:
        return ScenarioVerificationService.run_scenario_1(db)
    elif scenario_num == 2:
        return ScenarioVerificationService.run_scenario_2(db)
    elif scenario_num == 3:
        return ScenarioVerificationService.run_scenario_3(db)
    elif scenario_num == 4:
        return ScenarioVerificationService.run_scenario_4(db)
    elif scenario_num == 5:
        return ScenarioVerificationService.run_scenario_5(db)
    elif scenario_num == 6:
        return ScenarioVerificationService.run_scenario_6(db)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scenario number {scenario_num}. Must be between 1 and 6."
        )
