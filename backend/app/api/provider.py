from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional, Dict, Any

from app.providers.factory import get_payment_provider
from app.config.settings import settings
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

router = APIRouter(prefix="/provider", tags=["Payment Provider (Razorpay)"])

class CreateOrderRequest(BaseModel):
    amount: float
    currency: str = "INR"
    receipt: str
    notes: Optional[Dict[str, Any]] = None

class CreateLinkRequest(BaseModel):
    amount: float
    currency: str = "INR"
    customer_name: str
    customer_email: str
    customer_phone: Optional[str] = None
    description: str
    idempotency_key: str

@router.get("/status")
def get_provider_status(current_user: UserProfile = Depends(get_current_user)):
    """
    Returns active gateway provider metadata, masked credentials, and supported tools.
    Secrets and private tokens are NEVER exposed.
    """
    key_id = settings.RAZORPAY_KEY_ID or ""
    masked_key = f"{key_id[:8]}****" if len(key_id) >= 8 else "****"
    is_mock = key_id.startswith("rzp_test_mock") or not settings.RAZORPAY_KEY_SECRET

    return {
        "active_provider": "RazorpayProvider" if not is_mock else "RazorpayProvider (Simulated Test Sandbox)",
        "mode": settings.RAZORPAY_MODE,
        "masked_key_id": masked_key,
        "is_mock_sandbox": is_mock,
        "supported_tools": [
            "GetPayment",
            "GetPaymentStatus",
            "CreateOrder",
            "CreatePaymentLink",
            "RetryPayment",
            "VerifyWebhookSignature"
        ],
        "gateway_url": "https://api.razorpay.com/v1",
        "credential_isolation": "Strictly stored in backend environment variables, never accessible on clients."
    }

@router.post("/orders")
def create_order(
    payload: CreateOrderRequest,
    current_user: UserProfile = Depends(get_current_user)
):
    """Tool: CreateOrder with the payment gateway."""
    provider = get_payment_provider()
    res = provider.create_order(
        amount=payload.amount,
        currency=payload.currency,
        receipt=payload.receipt,
        notes=payload.notes
    )
    if "error" in res:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order creation failed: {res.get('error')}"
        )
    return {"status": "success", "order": res}

@router.get("/payments/{payment_id}")
def inspect_payment(
    payment_id: str,
    current_user: UserProfile = Depends(get_current_user)
):
    """Tool: GetPayment & GetPaymentStatus from gateway."""
    provider = get_payment_provider()
    status_info = provider.get_payment_status(payment_id)
    return {"status": "success", "payment": status_info}

@router.post("/payment-links")
def generate_payment_link(
    payload: CreateLinkRequest,
    current_user: UserProfile = Depends(get_current_user)
):
    """Tool: CreatePaymentLink for automated customer recovery."""
    provider = get_payment_provider()
    res = provider.create_payment_link(
        amount=payload.amount,
        currency=payload.currency,
        customer_name=payload.customer_name,
        customer_email=payload.customer_email,
        customer_phone=payload.customer_phone,
        description=payload.description,
        idempotency_key=payload.idempotency_key
    )
    if "error" in res:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment link creation failed: {res.get('error')}"
        )
    return {"status": "success", "payment_link": res}
