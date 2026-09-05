from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
import datetime

class PaymentCreate(BaseModel):
    id: str
    merchant_id: str
    customer_id: str
    amount: float
    currency: str = "INR"
    status: str = "FAILED"
    error_code: Optional[str] = None
    error_description: Optional[str] = None
    failure_reason: Optional[str] = None
    ai_diagnosis: Optional[str] = None
    recommended_action: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    recovery_status: str = "FAILED"

class PaymentResponse(BaseModel):
    id: str
    merchant_id: str
    customer_id: str
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    amount: float
    currency: str
    status: str
    error_code: Optional[str]
    failure_reason: Optional[str]
    ai_diagnosis: Optional[str]
    recommended_action: Optional[str]
    retry_count: int
    max_retries: int
    recovery_status: str
    risk_score: Optional[float] = None
    risk_level: Optional[str] = None
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)

class PaymentListResponse(BaseModel):
    items: List[PaymentResponse]
    total: int
    revenue_at_risk: float
    recoverable_revenue: float
    recovered_revenue: float
    in_review_count: int
