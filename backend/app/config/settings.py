from typing import List, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import json
import os

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    APP_PORT: int = 8000
    APP_HOST: str = "0.0.0.0"
    
    # Database
    DATABASE_URL: str = "sqlite:///./payment_recovery.db"
    
    # Security
    SECRET_KEY: str = "change_this_in_production_super_secret_key_12345"
    CORS_ORIGINS: Union[List[str], str] = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]
    
    @field_validator("CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return [i.strip() for i in v.split(",")]
        return v
    
    # Razorpay
    RAZORPAY_KEY_ID: str = "rzp_test_mock_key_id"
    RAZORPAY_KEY_SECRET: str = "rzp_test_mock_secret_key"
    RAZORPAY_MODE: str = "test"
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    
    # Safety Guardrails
    MAX_RETRY_ATTEMPTS: int = 3
    DEFAULT_RETRY_DELAY_HOURS: int = 24
    
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
