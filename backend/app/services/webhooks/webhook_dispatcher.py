"""
Phase 11: Outbound Webhook Dispatcher Service
==============================================
Responsible for:
  1. Registering / managing merchant webhook endpoints
  2. Dispatching signed HMAC-SHA256 webhook events to registered URLs
  3. Recording every dispatch attempt in webhook_deliveries
  4. Providing exponential-backoff retry eligibility checks

Event catalogue (subscribed_events wildcards supported with "*"):
  risk.assessed          - fired when RiskAssessmentService evaluates a payment
  recovery.decided       - fired when RecoveryDecisionService picks an action
  recovery.executed      - fired when RecoveryExecutionService fires an action
  review.quarantined     - fired when a payment enters human review queue
  review.decided         - fired when a reviewer submits APPROVE/REJECT/ESCALATE
  payment.status_changed - fired on any payment status transition

Dispatch is synchronous in this implementation (suitable for FastAPI background tasks
or direct call). In production, swap dispatch() for an async Celery/Redis task.

Signature scheme:
  X-Webhook-Signature: sha256=<HMAC-SHA256 hex(secret, raw_body)>
  X-Webhook-Timestamp: <UTC ISO-8601>
  X-Webhook-Event:     <event_type>
  X-Webhook-Version:   "1.0"
"""
import uuid
import hmac
import hashlib
import json
import datetime
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from app.models.webhook_endpoint import WebhookEndpoint, WebhookDelivery
from app.models.merchant import Merchant
from app.utils.logger import logger

# ── Constants ─────────────────────────────────────────────────────────────────

WEBHOOK_VERSION = "1.0"
DISPATCH_TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 4          # 1 initial + 3 retries
RETRY_DELAYS = [60, 300, 900]   # seconds: 1m, 5m, 15m

# ── Helpers ───────────────────────────────────────────────────────────────────

def _sign_payload(secret: str, raw_body: bytes) -> str:
    """Return HMAC-SHA256 hex digest of the raw body using the endpoint secret."""
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def _endpoint_subscribes(endpoint: WebhookEndpoint, event_type: str) -> bool:
    """Returns True if the endpoint's subscribed_events covers the given event_type."""
    subs = [s.strip() for s in (endpoint.subscribed_events or "*").split(",")]
    return "*" in subs or event_type in subs


def _make_payload(event_type: str, payment_id: Optional[str], data: Dict[str, Any]) -> Dict[str, Any]:
    """Build the standard outbound webhook envelope."""
    return {
        "api_version": WEBHOOK_VERSION,
        "event": event_type,
        "payment_id": payment_id,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "data": data,
    }


# ── Main Service ──────────────────────────────────────────────────────────────

class WebhookDispatcherService:

    # ── Endpoint Management ───────────────────────────────────────────────────

    @classmethod
    def register_endpoint(
        cls,
        db: Session,
        merchant_id: str,
        url: str,
        secret: str,
        description: str = "",
        subscribed_events: str = "*",
    ) -> WebhookEndpoint:
        """
        Register a new outbound webhook endpoint for a merchant.
        Returns the created WebhookEndpoint ORM object.
        """
        merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
        if not merchant:
            raise ValueError(f"Merchant '{merchant_id}' not found.")

        endpoint = WebhookEndpoint(
            id=f"whe_{uuid.uuid4().hex[:16]}",
            merchant_id=merchant_id,
            url=url,
            secret=secret,
            description=description,
            subscribed_events=subscribed_events,
            is_active=True,
        )
        db.add(endpoint)
        db.commit()
        db.refresh(endpoint)
        logger.info(f"[Webhook] Registered endpoint {endpoint.id} for merchant {merchant_id} -> {url}")
        return endpoint

    @classmethod
    def list_endpoints(cls, db: Session, merchant_id: str) -> List[WebhookEndpoint]:
        return (
            db.query(WebhookEndpoint)
            .filter(WebhookEndpoint.merchant_id == merchant_id)
            .order_by(WebhookEndpoint.created_at.desc())
            .all()
        )

    @classmethod
    def toggle_endpoint(cls, db: Session, endpoint_id: str, active: bool) -> WebhookEndpoint:
        endpoint = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).first()
        if not endpoint:
            raise ValueError(f"Endpoint '{endpoint_id}' not found.")
        endpoint.is_active = active
        db.commit()
        db.refresh(endpoint)
        return endpoint

    @classmethod
    def delete_endpoint(cls, db: Session, endpoint_id: str) -> None:
        endpoint = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).first()
        if not endpoint:
            raise ValueError(f"Endpoint '{endpoint_id}' not found.")
        db.delete(endpoint)
        db.commit()

    # ── Dispatch ──────────────────────────────────────────────────────────────

    @classmethod
    def dispatch_event(
        cls,
        db: Session,
        merchant_id: str,
        event_type: str,
        payment_id: Optional[str],
        data: Dict[str, Any],
    ) -> List[str]:
        """
        Fan-out: dispatch an event to all active, subscribed endpoints for a merchant.
        Returns list of WebhookDelivery IDs created.
        """
        endpoints = (
            db.query(WebhookEndpoint)
            .filter(
                WebhookEndpoint.merchant_id == merchant_id,
                WebhookEndpoint.is_active == True,
            )
            .all()
        )

        delivery_ids: List[str] = []
        for ep in endpoints:
            if not _endpoint_subscribes(ep, event_type):
                continue
            delivery_id = cls._dispatch_to_endpoint(db, ep, event_type, payment_id, data)
            delivery_ids.append(delivery_id)

        return delivery_ids

    @classmethod
    def _dispatch_to_endpoint(
        cls,
        db: Session,
        endpoint: WebhookEndpoint,
        event_type: str,
        payment_id: Optional[str],
        data: Dict[str, Any],
    ) -> str:
        """Execute a single HTTP POST dispatch and record the delivery attempt."""
        delivery_id = f"whd_{uuid.uuid4().hex[:16]}"
        payload = _make_payload(event_type, payment_id, data)
        raw_body = json.dumps(payload, default=str).encode("utf-8")
        signature = _sign_payload(endpoint.secret, raw_body)
        now = datetime.datetime.utcnow()

        # Create delivery log (PENDING)
        delivery = WebhookDelivery(
            id=delivery_id,
            endpoint_id=endpoint.id,
            payment_id=payment_id,
            event_type=event_type,
            payload=payload,
            status="PENDING",
            attempt_count=1,
            dispatched_at=now,
        )
        db.add(delivery)
        db.flush()

        # Build request
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Webhook-Timestamp": now.isoformat(),
            "X-Webhook-Event": event_type,
            "X-Webhook-Version": WEBHOOK_VERSION,
        }

        try:
            req = urllib.request.Request(
                url=endpoint.url,
                data=raw_body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=DISPATCH_TIMEOUT_SECONDS) as resp:
                http_status = resp.status
                response_body = resp.read(1024).decode("utf-8", errors="replace")

            if 200 <= http_status < 300:
                delivery.status = "SUCCESS"
                delivery.http_status = http_status
                delivery.response_body = response_body
                delivery.resolved_at = datetime.datetime.utcnow()
                logger.info(
                    f"[Webhook] Delivered {event_type} to {endpoint.url} "
                    f"({http_status}) delivery={delivery_id}"
                )
            else:
                delivery.status = "FAILED"
                delivery.http_status = http_status
                delivery.response_body = response_body
                delivery.error_message = f"Non-2xx response: {http_status}"
                cls._schedule_retry(delivery)
                logger.warning(
                    f"[Webhook] Non-2xx {http_status} for {event_type} -> {endpoint.url}"
                )

        except Exception as exc:
            delivery.status = "FAILED"
            delivery.error_message = str(exc)[:512]
            cls._schedule_retry(delivery)
            logger.warning(
                f"[Webhook] Dispatch error for {event_type} -> {endpoint.url}: {exc}"
            )

        db.commit()
        return delivery_id

    @classmethod
    def _schedule_retry(cls, delivery: WebhookDelivery) -> None:
        """Assign next_retry_at based on attempt_count using exponential backoff delays."""
        attempt_index = delivery.attempt_count - 1
        if attempt_index < len(RETRY_DELAYS):
            delay = RETRY_DELAYS[attempt_index]
            delivery.next_retry_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=delay)
            delivery.status = "RETRYING"
        else:
            delivery.status = "FAILED"  # exhausted retries
            delivery.next_retry_at = None

    @classmethod
    def retry_failed(cls, db: Session, delivery_id: str) -> str:
        """
        Manually trigger a retry for a specific FAILED or RETRYING delivery.
        Returns new status.
        """
        delivery = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).first()
        if not delivery:
            raise ValueError(f"Delivery '{delivery_id}' not found.")
        if delivery.status == "SUCCESS":
            return "SUCCESS"  # nothing to do

        endpoint = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == delivery.endpoint_id).first()
        if not endpoint:
            raise ValueError(f"Endpoint for delivery '{delivery_id}' not found.")

        delivery.attempt_count += 1
        raw_body = json.dumps(delivery.payload, default=str).encode("utf-8")
        signature = _sign_payload(endpoint.secret, raw_body)

        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Webhook-Timestamp": datetime.datetime.utcnow().isoformat(),
            "X-Webhook-Event": delivery.event_type,
            "X-Webhook-Version": WEBHOOK_VERSION,
        }
        try:
            req = urllib.request.Request(
                url=endpoint.url,
                data=raw_body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=DISPATCH_TIMEOUT_SECONDS) as resp:
                http_status = resp.status
                delivery.http_status = http_status
                delivery.response_body = resp.read(1024).decode("utf-8", errors="replace")

            if 200 <= http_status < 300:
                delivery.status = "SUCCESS"
                delivery.resolved_at = datetime.datetime.utcnow()
                delivery.next_retry_at = None
            else:
                cls._schedule_retry(delivery)

        except Exception as exc:
            delivery.error_message = str(exc)[:512]
            cls._schedule_retry(delivery)

        db.commit()
        return delivery.status

    # ── Delivery Logs ─────────────────────────────────────────────────────────

    @classmethod
    def get_deliveries(
        cls,
        db: Session,
        merchant_id: str,
        event_type: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        q = (
            db.query(WebhookDelivery)
            .join(WebhookEndpoint, WebhookEndpoint.id == WebhookDelivery.endpoint_id)
            .filter(WebhookEndpoint.merchant_id == merchant_id)
            .order_by(WebhookDelivery.dispatched_at.desc())
        )
        if event_type:
            q = q.filter(WebhookDelivery.event_type == event_type)
        if status_filter:
            q = q.filter(WebhookDelivery.status == status_filter)

        total = q.count()
        rows = q.offset(offset).limit(limit).all()

        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "deliveries": [
                {
                    "id": d.id,
                    "endpoint_id": d.endpoint_id,
                    "payment_id": d.payment_id,
                    "event_type": d.event_type,
                    "status": d.status,
                    "http_status": d.http_status,
                    "attempt_count": d.attempt_count,
                    "error_message": d.error_message,
                    "next_retry_at": d.next_retry_at.isoformat() if d.next_retry_at else None,
                    "dispatched_at": d.dispatched_at.isoformat(),
                    "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
                }
                for d in rows
            ],
        }
