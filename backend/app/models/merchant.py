import datetime
from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from app.database.session import Base

class Merchant(Base):
    __tablename__ = "merchants"

    id = Column(String(64), primary_key=True, index=True)
    business_name = Column(String(128), nullable=False)
    contact_email = Column(String(128), nullable=False)
    razorpay_key_id = Column(String(128), nullable=True)
    is_live = Column(Boolean, default=False) # False = Test Mode
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    users = relationship("User", back_populates="merchant")
    customers = relationship("Customer", back_populates="merchant")
    payments = relationship("Payment", back_populates="merchant")
    webhook_endpoints = relationship("WebhookEndpoint", back_populates="merchant",
                                    cascade="all, delete-orphan")

