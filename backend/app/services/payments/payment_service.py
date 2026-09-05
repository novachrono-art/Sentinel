from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from app.models.payment import Payment
from app.models.customer import Customer
from app.models.risk_assessment import RiskAssessment
from app.schemas.payment import PaymentCreate

class PaymentService:
    @staticmethod
    def get_payment_by_id(db: Session, payment_id: str) -> Optional[Payment]:
        return db.query(Payment).filter(Payment.id == payment_id).first()

    @staticmethod
    @staticmethod
    def list_payments(
        db: Session,
        status: Optional[str] = None,
        risk_level: Optional[str] = None,
        merchant_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Payment]:
        query = db.query(Payment)
        if merchant_id:
            query = query.filter(Payment.merchant_id == merchant_id)
        if status:
            query = query.filter(Payment.recovery_status == status)
        if risk_level:
            query = query.join(RiskAssessment).filter(RiskAssessment.risk_level == risk_level)
        return query.order_by(Payment.created_at.desc()).offset(skip).limit(limit).all()

    @staticmethod
    def get_metrics_summary(db: Session, merchant_id: Optional[str] = None) -> dict:
        query = db.query(Payment)
        if merchant_id:
            query = query.filter(Payment.merchant_id == merchant_id)
        payments = query.all()
        total_at_risk = sum(p.amount for p in payments if p.recovery_status != "RECOVERED" and p.status != "CAPTURED")
        recovered = sum(p.amount for p in payments if p.recovery_status == "RECOVERED" or p.status == "CAPTURED")
        recoverable = sum(p.amount for p in payments if (p.risk_assessment and p.risk_assessment.risk_level == "LOW" and p.retry_count < p.max_retries and p.recovery_status != "RECOVERED"))
        in_review = sum(1 for p in payments if (p.recovery_status == "IN_REVIEW" or (p.risk_assessment and p.risk_assessment.risk_level == "HIGH")) and p.recovery_status != "RECOVERED")
        
        return {
            "total_count": len(payments),
            "revenue_at_risk": total_at_risk,
            "recoverable_revenue": recoverable,
            "recovered_revenue": recovered,
            "in_review_count": in_review
        }


    @staticmethod
    def create_payment(db: Session, payment_in: PaymentCreate) -> Payment:
        db_payment = Payment(**payment_in.model_dump())
        db.add(db_payment)
        db.commit()
        db.refresh(db_payment)
        return db_payment
