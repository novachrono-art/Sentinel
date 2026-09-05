import datetime
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Text, Index
from sqlalchemy.orm import relationship
from app.database.session import Base

class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_merchant_status_created", "merchant_id", "status", "created_at"),
        Index("ix_payments_merchant_recovery_status", "merchant_id", "recovery_status"),
    )

    id = Column(String(64), primary_key=True, index=True) # e.g. pay_RP_001
    merchant_id = Column(String(64), ForeignKey("merchants.id"), nullable=False)
    customer_id = Column(String(64), ForeignKey("customers.id"), nullable=False)
    
    amount = Column(Float, nullable=False)
    currency = Column(String(8), default="INR")
    
    # Status: "FAILED" | "RECOVERED" | "HELD" | "SCHEDULED" | "IN_REVIEW" | "PROCESSING"
    status = Column(String(32), default="FAILED", index=True)
    
    # Error & Failure Diagnostics
    error_code = Column(String(64), nullable=True) # e.g. "BANK_DECLINE_TEMPORARY"
    error_description = Column(Text, nullable=True)
    failure_reason = Column(Text, nullable=True)
    
    # AI Diagnosis & Context
    ai_diagnosis = Column(Text, nullable=True)
    recommended_action = Column(String(64), nullable=True)
    
    # Guardrails & Retries
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    recovery_status = Column(String(32), default="FAILED", index=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    merchant = relationship("Merchant", back_populates="payments")
    customer = relationship("Customer", back_populates="payments")
    attempts = relationship("PaymentAttempt", back_populates="payment", cascade="all, delete-orphan")
    risk_assessment = relationship("RiskAssessment", back_populates="payment", uselist=False, cascade="all, delete-orphan")
    recovery_actions = relationship("RecoveryAction", back_populates="payment", cascade="all, delete-orphan")
    human_review = relationship("HumanReview", back_populates="payment", uselist=False, cascade="all, delete-orphan")
    audit_events = relationship("AuditEvent", back_populates="payment", cascade="all, delete-orphan")
