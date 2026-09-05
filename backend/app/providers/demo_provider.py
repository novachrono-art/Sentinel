import uuid
import datetime
import time
from typing import Dict, Any, Optional
from app.providers.base import PaymentProvider

class DemoPaymentProvider(PaymentProvider):
    """
    Deterministic Synthetic Provider for testing failure triage, risk quarantine, and recovery workflows.
    """

    def get_payment(self, payment_id: str) -> Dict[str, Any]:
        return {
            "id": payment_id,
            "entity": "payment",
            "amount": 499900,
            "currency": "INR",
            "status": "failed",
            "method": "card",
            "error_code": "BAD_REQUEST_ERROR",
            "error_description": "Payment was declined by issuing bank",
            "error_source": "bank",
            "error_step": "payment_authorization",
            "error_reason": "payment_failed",
            "created_at": int(time.time())
        }

    def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        return {
            "payment_id": payment_id,
            "status": "failed",
            "amount": 4999.0,
            "currency": "INR",
            "method": "card",
            "captured": False,
            "error_code": "BAD_REQUEST_ERROR",
            "error_description": "Payment was declined by issuing bank",
            "is_recovered": False
        }

    def create_order(
        self,
        amount: float,
        currency: str,
        receipt: str,
        notes: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        order_id = f"order_demo_{uuid.uuid4().hex[:10]}"
        amount_paise = int(round(amount * 100))
        return {
            "id": order_id,
            "entity": "order",
            "amount": amount_paise,
            "amount_paid": 0,
            "amount_due": amount_paise,
            "currency": currency,
            "receipt": receipt,
            "status": "created",
            "notes": notes or {},
            "created_at": int(time.time())
        }

    def create_payment_link(
        self,
        amount: float,
        currency: str,
        customer_name: str,
        customer_email: str,
        description: str,
        idempotency_key: str,
        customer_phone: Optional[str] = None,
        expire_by_hours: int = 24
    ) -> Dict[str, Any]:
        link_id = f"plink_demo_{uuid.uuid4().hex[:10]}"
        return {
            "id": link_id,
            "short_url": f"https://rzp.io/i/{link_id}",
            "amount": int(round(amount * 100)),
            "currency": currency,
            "status": "created",
            "customer": {"name": customer_name, "email": customer_email, "contact": customer_phone},
            "idempotency_key": idempotency_key,
            "created_at": datetime.datetime.utcnow().isoformat()
        }

    def retry_payment(self, payment_id: str, idempotency_key: str) -> Dict[str, Any]:
        return {
            "id": f"pay_retry_{uuid.uuid4().hex[:8]}",
            "original_payment_id": payment_id,
            "status": "captured",
            "idempotency_key": idempotency_key,
            "message": "Demo simulated payment recovery succeeded"
        }

    def verify_webhook_signature(self, payload_body: bytes, signature: str, secret: str) -> bool:
        return True
