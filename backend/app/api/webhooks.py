from fastapi import APIRouter, Request, HTTPException, status, Header, Depends
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.services.ingestion.ingestion_service import IngestionService
from app.providers.factory import get_payment_provider
from app.config.settings import settings
from app.utils.logger import logger

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

@router.post("/razorpay")
async def handle_razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None),
    db: Session = Depends(get_db)
):
    body_bytes = await request.body()
    provider = get_payment_provider()
    
    # In live/test mode, verify cryptographic webhook signature
    if settings.RAZORPAY_KEY_SECRET and x_razorpay_signature:
        is_valid = provider.verify_webhook_signature(
            payload_body=body_bytes,
            signature=x_razorpay_signature,
            secret=settings.RAZORPAY_KEY_SECRET
        )
        if not is_valid:
            logger.warning("Rejected Razorpay webhook with invalid signature")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Razorpay webhook signature"
            )

    try:
        event_data = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON in webhook body"
        )

    event_type = event_data.get("event")
    logger.info(f"Received Razorpay webhook event: {event_type}")

    payment = IngestionService.ingest_webhook_event(db, event_data)
    
    return {
        "status": "success",
        "event": event_type,
        "payment_id": payment.id,
        "amount": payment.amount
    }
