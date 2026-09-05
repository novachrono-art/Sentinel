import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.database.session import Base

class RecoveryAction(Base):
    __tablename__ = "recovery_actions"

    id = Column(String(64), primary_key=True, index=True)
    payment_id = Column(String(64), ForeignKey("payments.id"), nullable=False)
    
    # Action type: "RETRY" | "CREATE_PAYMENT_LINK" | "SEND_REMINDER" | "WAIT" | "ESCALATE"
    action_type = Column(String(64), nullable=False)
    idempotency_key = Column(String(128), unique=True, index=True, nullable=False)
    
    status = Column(String(32), default="PENDING") # "PENDING" | "EXECUTED" | "FAILED" | "BLOCKED"
    payload = Column(JSON, nullable=True)
    execution_result = Column(JSON, nullable=True)
    
    executed_by = Column(String(64), default="AI_AGENT") # "AI_AGENT" | "MERCHANT_MANUAL" | "REVIEWER_OVERRIDE"
    executed_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    payment = relationship("Payment", back_populates="recovery_actions")
