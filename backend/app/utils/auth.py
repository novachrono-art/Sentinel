import jwt
import datetime
from typing import Optional, List, Dict
from fastapi import HTTPException, Security, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config.settings import settings
from app.schemas.auth import UserProfile

security = HTTPBearer(auto_error=False)

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Seeded Prototype User Accounts
DEMO_USERS: Dict[str, dict] = {
    "admin@razorpay-recovery.io": {
        "id": "usr_admin_001",
        "name": "Platform Admin",
        "email": "admin@razorpay-recovery.io",
        "password": "adminpassword123",
        "role": "admin",
        "merchant_id": "mer_demo_apex",
        "is_active": True
    },
    "merchant@razorpay-recovery.io": {
        "id": "usr_merchant_001",
        "name": "Sarah Merchant",
        "email": "merchant@razorpay-recovery.io",
        "password": "merchantpassword123",
        "role": "merchant",
        "merchant_id": "mer_demo_apex",
        "is_active": True
    },

    "reviewer@razorpay-recovery.io": {
        "id": "usr_reviewer_002",
        "name": "Alex Risk Officer",
        "email": "reviewer@razorpay-recovery.io",
        "password": "reviewerpassword123",
        "role": "reviewer",
        "merchant_id": None,
        "is_active": True
    }
}

def create_access_token(user_email: str, role: str, expires_delta: Optional[datetime.timedelta] = None) -> str:
    if expires_delta:
        expire = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    else:
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=JWT_EXPIRATION_HOURS)
    
    payload = {
        "sub": user_email,
        "role": role,
        "exp": expire,
        "iat": datetime.datetime.now(datetime.timezone.utc)
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)) -> UserProfile:
    # 1. Fallback for unauthenticated dev or frontend placeholder dev token
    if not credentials or credentials.credentials in ("demo_dev_jwt_token_active", "demo_token", "dev_token"):
        user_dict = DEMO_USERS["admin@razorpay-recovery.io"]
        return UserProfile(
            id=user_dict["id"],
            name=user_dict["name"],
            email=user_dict["email"],
            role=user_dict["role"],
            merchant_id=user_dict.get("merchant_id"),
            is_active=True
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
        email: str = payload.get("sub")
        if email is None or email not in DEMO_USERS:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_dict = DEMO_USERS[email]
        return UserProfile(
            id=user_dict["id"],
            name=user_dict["name"],
            email=user_dict["email"],
            role=user_dict["role"],
            merchant_id=user_dict.get("merchant_id"),
            is_active=user_dict.get("is_active", True)
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token signature expired or invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_role(allowed_roles: List[str]):
    def role_checker(current_user: UserProfile = Depends(get_current_user)) -> UserProfile:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Action requires one of roles {allowed_roles}. Current role: '{current_user.role}'."
            )
        return current_user
    return role_checker
