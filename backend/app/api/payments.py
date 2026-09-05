from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database.session import get_db
from app.schemas.payment import PaymentResponse, PaymentListResponse
from app.services.payments.payment_service import PaymentService
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

router = APIRouter(prefix="/payments", tags=["Payments"])

@router.get("", response_model=PaymentListResponse)
def list_payments(
    status: Optional[str] = None,
    risk_level: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    # Multi-tenant isolation: Merchants only see their own transactions; Admins/Reviewers see global
    merchant_id = current_user.merchant_id if current_user.role == "merchant" else None
    payments = PaymentService.list_payments(db, status=status, risk_level=risk_level, merchant_id=merchant_id, skip=skip, limit=limit)
    metrics = PaymentService.get_metrics_summary(db, merchant_id=merchant_id)

    
    items = []
    for p in payments:
        items.append(
            PaymentResponse(
                id=p.id,
                merchant_id=p.merchant_id,
                customer_id=p.customer_id,
                customer_name=p.customer.name if p.customer else None,
                customer_email=p.customer.email if p.customer else None,
                amount=p.amount,
                currency=p.currency,
                status=p.status,
                error_code=p.error_code,
                failure_reason=p.failure_reason,
                ai_diagnosis=p.ai_diagnosis,
                recommended_action=p.recommended_action,
                retry_count=p.retry_count,
                max_retries=p.max_retries,
                recovery_status=p.recovery_status,
                risk_score=p.risk_assessment.risk_score if p.risk_assessment else None,
                risk_level=p.risk_assessment.risk_level if p.risk_assessment else None,
                created_at=p.created_at
            )
        )
    
    return PaymentListResponse(
        items=items,
        total=metrics["total_count"],
        revenue_at_risk=metrics["revenue_at_risk"],
        recoverable_revenue=metrics["recoverable_revenue"],
        recovered_revenue=metrics["recovered_revenue"],
        in_review_count=metrics["in_review_count"]
    )

@router.get("/metrics")
def get_metrics_summary(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    return PaymentService.get_metrics_summary(db)

@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment_details(
    payment_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user)
):
    p = PaymentService.get_payment_by_id(db, payment_id)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment transaction with ID '{payment_id}' was not found."
        )
    
    return PaymentResponse(
        id=p.id,
        merchant_id=p.merchant_id,
        customer_id=p.customer_id,
        customer_name=p.customer.name if p.customer else None,
        customer_email=p.customer.email if p.customer else None,
        amount=p.amount,
        currency=p.currency,
        status=p.status,
        error_code=p.error_code,
        failure_reason=p.failure_reason,
        ai_diagnosis=p.ai_diagnosis,
        recommended_action=p.recommended_action,
        retry_count=p.retry_count,
        max_retries=p.max_retries,
        recovery_status=p.recovery_status,
        risk_score=p.risk_assessment.risk_score if p.risk_assessment else None,
        risk_level=p.risk_assessment.risk_level if p.risk_assessment else None,
        created_at=p.created_at
    )
