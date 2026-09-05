import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, JSON, Index
from sqlalchemy.orm import relationship
from app.database.session import Base

class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_payment_timestamp", "payment_id", "timestamp"),
        Index("ix_audit_event_type_timestamp", "event_type", "timestamp"),
    )

    id = Column(String(64), primary_key=True, index=True)
    payment_id = Column(String(64), ForeignKey("payments.id"), nullable=False, index=True)
    agent_run_id = Column(String(64), nullable=True)
    
    event_type = Column(String(64), nullable=False, index=True)
    actor = Column(String(64), nullable=False) # e.g. "Deterministic Risk Classifier", "LangGraph Agent", "Merchant Operator"
    
    details = Column(Text, nullable=False)
    risk_level = Column(String(16), nullable=True)
    outcome = Column(String(32), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    # Relationships
    payment = relationship("Payment", back_populates="audit_events")
