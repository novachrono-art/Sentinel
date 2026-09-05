import datetime
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.database.session import Base

class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id = Column(String(64), primary_key=True, index=True)
    payment_id = Column(String(64), ForeignKey("payments.id"), unique=True, nullable=False)
    
    risk_score = Column(Float, nullable=False) # e.g. 0.18
    risk_level = Column(String(16), nullable=False) # "LOW" | "MEDIUM" | "HIGH"
    model_version = Column(String(64), default="LogisticRegression-v1.0")
    
    # Feature vectors & Explanation
    features_used = Column(JSON, nullable=True) # Dict of extracted features
    signals = Column(JSON, nullable=True) # List of textual signals
    explanation = Column(Text, nullable=True)
    
    evaluated_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    payment = relationship("Payment", back_populates="risk_assessment")
