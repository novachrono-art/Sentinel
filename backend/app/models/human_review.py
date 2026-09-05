import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.database.session import Base

class HumanReview(Base):
    __tablename__ = "human_reviews"

    id = Column(String(64), primary_key=True, index=True)
    payment_id = Column(String(64), ForeignKey("payments.id"), unique=True, nullable=False)
    reviewer_id = Column(String(64), ForeignKey("users.id"), nullable=True)
    
    # Status: "PENDING" | "APPROVED" | "REJECTED" | "ESCALATED"
    status = Column(String(32), default="PENDING", index=True)
    reason_for_quarantine = Column(Text, nullable=False)
    
    decision = Column(String(32), nullable=True) # "APPROVE" | "REJECT" | "ESCALATE"
    decision_notes = Column(Text, nullable=True)
    
    quarantined_at = Column(DateTime, default=datetime.datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    # Relationships
    payment = relationship("Payment", back_populates="human_review")
    reviewer = relationship("User", back_populates="human_reviews")
