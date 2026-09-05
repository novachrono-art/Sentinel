import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database.session import Base

class User(Base):
    __tablename__ = "users"

    id = Column(String(64), primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    email = Column(String(128), unique=True, index=True, nullable=False)
    password_hash = Column(String(256), nullable=True)
    role = Column(String(32), nullable=False, default="merchant") # "merchant" | "reviewer"
    merchant_id = Column(String(64), ForeignKey("merchants.id"), nullable=True)
    picture = Column(String(512), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    merchant = relationship("Merchant", back_populates="users")
    human_reviews = relationship("HumanReview", back_populates="reviewer")
