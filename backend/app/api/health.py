from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.session import get_db
from app.config.settings import settings
import datetime

router = APIRouter(prefix="/health", tags=["Health"])

@router.get("")
def check_health(db: Session = Depends(get_db)):
    db_status = "healthy"
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    
    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "service": "TheSentinel Recovery API",
        "environment": settings.ENVIRONMENT,
        "database": db_status,
        "max_retry_attempts": settings.MAX_RETRY_ATTEMPTS,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
