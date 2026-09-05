"""
WebhookEndpoint — merchant-registered outbound webhook URL.
WebhookDelivery  — per-dispatch delivery log with retry tracking.
"""
import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, Text, JSON
from sqlalchemy.orm import relationship
from app.database.session import Base


class WebhookEndpoint(Base):
    """Stores a merchant's registered outbound webhook URL and its subscription config."""
    __tablename__ = "webhook_endpoints"

    id           = Column(String(64),  primary_key=True, index=True)
    merchant_id  = Column(String(64),  ForeignKey("merchants.id"), nullable=False, index=True)

    url          = Column(String(512), nullable=False)
    secret       = Column(String(128), nullable=False)   # HMAC signing secret (stored hashed in prod)
    description  = Column(String(256), nullable=True)

    # Comma-separated event subscriptions, e.g. "risk.assessed,recovery.executed,review.decided"
    subscribed_events = Column(Text, nullable=False, default="*")

    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.datetime.utcnow,
                          onupdate=datetime.datetime.utcnow)

    # Relationships
    merchant     = relationship("Merchant", back_populates="webhook_endpoints")
    deliveries   = relationship("WebhookDelivery", back_populates="endpoint",
                                cascade="all, delete-orphan")


class WebhookDelivery(Base):
    """Per-dispatch delivery record — one row per attempt."""
    __tablename__ = "webhook_deliveries"

    id           = Column(String(64),  primary_key=True, index=True)
    endpoint_id  = Column(String(64),  ForeignKey("webhook_endpoints.id"), nullable=False, index=True)
    payment_id   = Column(String(64),  nullable=True, index=True)

    event_type   = Column(String(64),  nullable=False)   # e.g. "risk.assessed"
    payload      = Column(JSON,        nullable=False)    # the full JSON body sent

    # Delivery outcome
    status       = Column(String(32),  default="PENDING", index=True)
    # "PENDING" | "SUCCESS" | "FAILED" | "RETRYING"

    http_status  = Column(Integer,  nullable=True)        # response status code received
    response_body = Column(Text,    nullable=True)        # first 1024 chars of response
    error_message = Column(Text,    nullable=True)        # network / timeout error text

    attempt_count = Column(Integer, default=0)
    next_retry_at = Column(DateTime, nullable=True)

    dispatched_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    resolved_at   = Column(DateTime, nullable=True)

    # Relationships
    endpoint     = relationship("WebhookEndpoint", back_populates="deliveries")
