import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from app.database.session import Base

class Customer(Base):
    __tablename__ = "customers"

    id = Column(String(64), primary_key=True, index=True)
    merchant_id = Column(String(64), ForeignKey("merchants.id"), nullable=False)
    name = Column(String(128), nullable=False)
    email = Column(String(128), index=True, nullable=False)
    phone = Column(String(32), nullable=True)
    lifetime_successful_orders = Column(Integer, default=0)
    lifetime_failed_orders = Column(Integer, default=0)
    total_spend = Column(Float, default=0.0)
    dispute_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    merchant = relationship("Merchant", back_populates="customers")
    payments = relationship("Payment", back_populates="customer")
