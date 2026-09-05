from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
import time
from contextlib import asynccontextmanager
from app.config.settings import settings
from app.utils.logger import logger
from app.database.init_db import init_db
from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.payments import router as payments_router
from app.api.webhooks import router as webhooks_router
from app.api.ingestion import router as ingestion_router
from app.api.risk import router as risk_router
from app.api.agent import router as agent_router
from app.api.recovery import router as recovery_router
from app.api.provider import router as provider_router
from app.api.execution import router as execution_router
from app.api.analytics import router as analytics_router
from app.api.review import router as review_router
from app.api.outbound_webhooks import router as outbound_webhooks_router
from app.api.audit import router as audit_router
from app.api.batch_recovery import router as batch_router
from app.api.scenarios import router as scenarios_router
from app.api.security import router as security_router
from app.api.performance import router as performance_router
from app.api.demo import router as demo_router
from app.middleware.security import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on application startup
    logger.info("Initializing SQLite database tables...")
    init_db()
    logger.info("Database schema initialized.")
    yield

app = FastAPI(
    title="TheSentinel — Autonomous Payment Failure Triage & Revenue Recovery API",
    description="Autonomous Deterministic Risk Triage & Revenue Recovery System with Razorpay Integration",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(SecurityHeadersMiddleware)

# Request Timing & Audit Logger Middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(f"{request.method} {request.url.path} - Status: {response.status_code} - Duration: {duration:.4f}s")
    return response

# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled Exception at {request.url.path}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "InternalServerError", "message": "An unexpected error occurred. This has been logged."},
    )

# Include API Routers
app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(payments_router, prefix="/api")
app.include_router(webhooks_router, prefix="/api")
app.include_router(ingestion_router, prefix="/api")
app.include_router(risk_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(recovery_router, prefix="/api")
app.include_router(provider_router, prefix="/api")
app.include_router(execution_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(review_router, prefix="/api")
app.include_router(outbound_webhooks_router, prefix="/api")
app.include_router(audit_router, prefix="/api")
app.include_router(batch_router, prefix="/api")
app.include_router(scenarios_router, prefix="/api")
app.include_router(security_router, prefix="/api")
app.include_router(performance_router, prefix="/api")
app.include_router(demo_router, prefix="/api")



@app.get("/")
def root():
    return {
        "message": "AI Payment Recovery Agent API is active.",
        "documentation": "/docs",
        "health_check": "/api/health"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.APP_HOST, port=settings.APP_PORT, reload=True)
