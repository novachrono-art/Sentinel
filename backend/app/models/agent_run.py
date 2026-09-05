import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.database.session import Base

class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String(64), primary_key=True, index=True)
    payment_id = Column(String(64), ForeignKey("payments.id"), nullable=False)
    
    initial_state = Column(JSON, nullable=True)
    final_state = Column(JSON, nullable=True)
    status = Column(String(32), default="RUNNING") # "RUNNING" | "COMPLETED" | "ESCALATED" | "FAILED"
    
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
