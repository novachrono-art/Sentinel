from pydantic import BaseModel, EmailStr
from typing import Optional

class LoginRequest(BaseModel):
    email: str
    password: str

class GoogleLoginRequest(BaseModel):
    credential: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = "merchant"

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str
    email: str
    picture: Optional[str] = None

class UserProfile(BaseModel):
    id: str
    name: str
    email: str
    role: str # "merchant" | "reviewer"
    merchant_id: Optional[str] = None
    picture: Optional[str] = None
    is_active: bool = True
