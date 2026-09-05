"""
Phase 11: Outbound Webhook Management API
==========================================
Endpoints:
  POST   /api/webhooks/endpoints                       - Register a new webhook endpoint
  GET    /api/webhooks/endpoints                       - List merchant's endpoints
  PATCH  /api/webhooks/endpoints/{endpoint_id}/toggle  - Enable / disable an endpoint
  DELETE /api/webhooks/endpoints/{endpoint_id}         - Delete an endpoint
  POST   /api/webhooks/test/{endpoint_id}              - Send a test ping event
  GET    /api/webhooks/deliveries                      - Delivery log (filterable)
  POST   /api/webhooks/deliveries/{delivery_id}/retry  - Manually retry a delivery
  GET    /api/webhooks/deliveries/{delivery_id}        - Single delivery detail

Access control:
  - Merchants can manage only their own endpoints (scoped by merchant_id).
  - Admins / reviewers see all merchants' endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.orm import Session
from typing import Optional, List
import datetime

from app.database.session import get_db
from app.models.webhook_endpoint import WebhookEndpoint, WebhookDelivery
from app.services.webhooks.webhook_dispatcher import WebhookDispatcherService
from app.utils.auth import get_current_user
from app.schemas.auth import UserProfile

router = APIRouter(prefix="/webhooks", tags=["Outbound Webhooks"])


# ── RBAC helper ───────────────────────────────────────────────────────────────

def _resolve_merchant_id(current_user: UserProfile, requested_merchant_id: Optional[str] = None) -> str:
    """
    For merchants, always return their own merchant_id (ignore requested value).
    For admin/reviewer, return requested_merchant_id if supplied, else raise.
    """
    if current_user.role == "merchant":
        if not current_user.merchant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Merchant account has no merchant_id associated.")
        return current_user.merchant_id
    # admin / reviewer
    if not requested_merchant_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Admin/reviewer must supply merchant_id query parameter.")
    return requested_merchant_id


def _assert_endpoint_ownership(endpoint: WebhookEndpoint, current_user: UserProfile):
    """Ensures a merchant can only touch their own endpoints."""
    if current_user.role == "merchant" and endpoint.merchant_id != current_user.merchant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You do not have permission to manage this endpoint.")


# ── Request / Response bodies ─────────────────────────────────────────────────

class RegisterEndpointRequest(BaseModel):
    url: str = Field(..., description="HTTPS URL that will receive webhook POST requests")
    secret: str = Field(..., min_length=8, max_length=128,
                        description="Shared HMAC secret for signature verification")
    description: Optional[str] = Field(None, max_length=256)
    subscribed_events: str = Field(
        "*",
        description="Comma-separated event types, or '*' for all. "
                    "e.g. 'risk.assessed,recovery.executed'"
    )


class ToggleRequest(BaseModel):
    active: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/endpoints", status_code=status.HTTP_201_CREATED)
def register_endpoint(
    body: RegisterEndpointRequest,
    merchant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """Register a new outbound webhook endpoint for a merchant."""
    mid = _resolve_merchant_id(current_user, merchant_id)
    try:
        ep = WebhookDispatcherService.register_endpoint(
            db=db,
            merchant_id=mid,
            url=body.url,
            secret=body.secret,
            description=body.description or "",
            subscribed_events=body.subscribed_events,
        )
        return {
            "id": ep.id,
            "merchant_id": ep.merchant_id,
            "url": ep.url,
            "description": ep.description,
            "subscribed_events": ep.subscribed_events,
            "is_active": ep.is_active,
            "created_at": ep.created_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/endpoints")
def list_endpoints(
    merchant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """List all webhook endpoints registered for a merchant."""
    mid = _resolve_merchant_id(current_user, merchant_id)
    endpoints = WebhookDispatcherService.list_endpoints(db=db, merchant_id=mid)
    return {
        "merchant_id": mid,
        "endpoints": [
            {
                "id": ep.id,
                "url": ep.url,
                "description": ep.description,
                "subscribed_events": ep.subscribed_events,
                "is_active": ep.is_active,
                "created_at": ep.created_at.isoformat(),
            }
            for ep in endpoints
        ],
    }


@router.patch("/endpoints/{endpoint_id}/toggle")
def toggle_endpoint(
    endpoint_id: str,
    body: ToggleRequest,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """Enable or disable a webhook endpoint."""
    ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Endpoint '{endpoint_id}' not found.")
    _assert_endpoint_ownership(ep, current_user)
    try:
        updated = WebhookDispatcherService.toggle_endpoint(db=db, endpoint_id=endpoint_id, active=body.active)
        return {"id": updated.id, "is_active": updated.is_active}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.delete("/endpoints/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_endpoint(
    endpoint_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """Permanently delete a webhook endpoint and all its delivery history."""
    ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Endpoint '{endpoint_id}' not found.")
    _assert_endpoint_ownership(ep, current_user)
    WebhookDispatcherService.delete_endpoint(db=db, endpoint_id=endpoint_id)


@router.post("/test/{endpoint_id}")
def send_test_ping(
    endpoint_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Sends a test 'webhook.ping' event to the specified endpoint.
    Useful for verifying connectivity and signature validation on the merchant's side.
    """
    ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Endpoint '{endpoint_id}' not found.")
    _assert_endpoint_ownership(ep, current_user)

    delivery_ids = WebhookDispatcherService.dispatch_event(
        db=db,
        merchant_id=ep.merchant_id,
        event_type="webhook.ping",
        payment_id=None,
        data={
            "message": "This is a test ping from the Razorpay Recovery Agent.",
            "endpoint_id": endpoint_id,
            "triggered_by": current_user.email,
        },
    )

    # fetch delivery result
    if delivery_ids:
        d = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_ids[0]).first()
        return {
            "delivery_id": d.id,
            "status": d.status,
            "http_status": d.http_status,
            "error_message": d.error_message,
        }
    return {"status": "NO_ACTIVE_ENDPOINTS"}


@router.get("/deliveries")
def list_deliveries(
    merchant_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    delivery_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Returns the paginated delivery log for a merchant, newest-first.
    Filter by event_type or status (SUCCESS | FAILED | RETRYING | PENDING).
    """
    mid = _resolve_merchant_id(current_user, merchant_id)
    return WebhookDispatcherService.get_deliveries(
        db=db,
        merchant_id=mid,
        event_type=event_type,
        status_filter=delivery_status,
        limit=limit,
        offset=offset,
    )


@router.get("/deliveries/{delivery_id}")
def get_delivery_detail(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """Returns full detail for a single delivery including payload and response body."""
    d = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Delivery '{delivery_id}' not found.")

    ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == d.endpoint_id).first()
    if current_user.role == "merchant" and ep and ep.merchant_id != current_user.merchant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Access denied to this delivery record.")

    return {
        "id": d.id,
        "endpoint_id": d.endpoint_id,
        "endpoint_url": ep.url if ep else None,
        "payment_id": d.payment_id,
        "event_type": d.event_type,
        "payload": d.payload,
        "status": d.status,
        "http_status": d.http_status,
        "response_body": d.response_body,
        "error_message": d.error_message,
        "attempt_count": d.attempt_count,
        "next_retry_at": d.next_retry_at.isoformat() if d.next_retry_at else None,
        "dispatched_at": d.dispatched_at.isoformat(),
        "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
    }


@router.post("/deliveries/{delivery_id}/retry")
def retry_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    """Manually trigger a re-delivery for a FAILED or RETRYING delivery."""
    d = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Delivery '{delivery_id}' not found.")

    ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == d.endpoint_id).first()
    if current_user.role == "merchant" and ep and ep.merchant_id != current_user.merchant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    try:
        new_status = WebhookDispatcherService.retry_failed(db=db, delivery_id=delivery_id)
        return {"delivery_id": delivery_id, "status": new_status}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
