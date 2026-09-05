import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.database.session import Base

class BatchRun(Base):
    __tablename__ = "batch_runs"

    id = Column(String(64), primary_key=True, index=True)
    merchant_id = Column(String(64), ForeignKey("merchants.id"), nullable=True, index=True)
    triggered_by = Column(String(128), default="SYSTEM")
    
    # Status: "RUNNING" | "COMPLETED" | "FAILED" | "PARTIAL"
    status = Column(String(32), default="RUNNING", index=True)
    
    # Counts
    total_payments = Column(Integer, default=0)
    processed_count = Column(Integer, default=0)
    recovered_count = Column(Integer, default=0)
    quarantined_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    
    # Financial metrics
    revenue_at_risk = Column(Float, default=0.0)
    revenue_recovered = Column(Float, default=0.0)
    recovery_rate = Column(Float, default=0.0) # percentage 0 - 100
    avg_attempts = Column(Float, default=0.0)
    escalation_rate = Column(Float, default=0.0) # percentage 0 - 100
    
    # Demo flag
    is_demo = Column(Boolean, default=False)
    
    # Context & Breakdown
    parameters_json = Column(JSON, nullable=True)
    metrics_json = Column(JSON, nullable=True)
    
    started_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    # Relationships
    merchant = relationship("Merchant")
    items = relationship("BatchRunItem", back_populates="batch_run", cascade="all, delete-orphan",
                         order_by="BatchRunItem.processed_at.asc()")


class BatchRunItem(Base):
    __tablename__ = "batch_run_items"

    id = Column(String(64), primary_key=True, index=True)
    batch_run_id = Column(String(64), ForeignKey("batch_runs.id"), nullable=False, index=True)
    payment_id = Column(String(64), ForeignKey("payments.id"), nullable=False, index=True)
    
    initial_status = Column(String(32), nullable=True)
    final_status = Column(String(32), nullable=True)
    risk_score = Column(Float, nullable=True)
    risk_level = Column(String(16), nullable=True)
    amount = Column(Float, default=0.0)
    recovery_action = Column(String(64), nullable=True)
    outcome = Column(String(32), index=True) # "RECOVERED" | "QUARANTINED" | "FAILED" | "SKIPPED"
    details = Column(Text, nullable=True)
    processed_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    batch_run = relationship("BatchRun", back_populates="items")
    payment = relationship("Payment")
