import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, Float
from sqlalchemy.orm import relationship
from app.database.session import Base

class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    id = Column(String(64), primary_key=True, index=True)
    payment_id = Column(String(64), ForeignKey("payments.id"), nullable=False)
    attempt_number = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False) # "SUCCESS" | "FAILED" | "TIMEOUT"
    gateway_response_code = Column(String(64), nullable=True)
    gateway_response_body = Column(Text, nullable=True)
    latency_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    payment = relationship("Payment", back_populates="attempts")
