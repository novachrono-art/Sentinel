from fastapi import APIRouter, HTTPException, status, Depends
import jwt
import requests
from app.schemas.auth import LoginRequest, GoogleLoginRequest, TokenResponse, UserProfile
from app.utils.auth import (
    DEMO_USERS,
    create_access_token,
    get_current_user,
    require_role
)
from app.config.settings import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/login", response_model=TokenResponse)
def login(credentials: LoginRequest):
    email = credentials.email.strip().lower()
    user = DEMO_USERS.get(email)
    
    if not user or user["password"] != credentials.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    token = create_access_token(user_email=user["email"], role=user["role"])
    
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        role=user["role"],
        name=user["name"],
        email=user["email"],
        picture=user.get("picture")
    )

@router.post("/google", response_model=TokenResponse)
def google_auth(payload: GoogleLoginRequest):
    email = payload.email
    name = payload.name or "Google User"
    picture = None
    role = payload.role or "merchant"

    # If a real Google Credential (JWT ID Token) was supplied by Google Identity Services SDK
    if payload.credential:
        try:
            # Decode Google JWT unverified or verify against Google tokeninfo
            decoded = jwt.decode(payload.credential, options={"verify_signature": False})
            email = decoded.get("email", email)
            name = decoded.get("name", name)
            picture = decoded.get("picture")
        except Exception:
            # Fallback to direct parameters if decoding fails
            pass
    
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Authentication failed: missing email address in credential"
        )

    email = email.strip().lower()

    # If user exists in registry, maintain their existing role
    if email in DEMO_USERS:
        user = DEMO_USERS[email]
        role = user.get("role", role)
        name = user.get("name", name)
        picture = picture or user.get("picture")
    else:
        # Register new Google authenticated user
        DEMO_USERS[email] = {
            "id": f"usr_google_{abs(hash(email)) % 100000}",
            "name": name,
            "email": email,
            "password": "", # OAuth user
            "role": role,
            "picture": picture,
            "merchant_id": "mer_google_auth_01",
            "is_active": True
        }

    token = create_access_token(user_email=email, role=role)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        role=role,
        name=name,
        email=email,
        picture=picture
    )

@router.get("/me", response_model=UserProfile)
def get_current_user_profile(current_user: UserProfile = Depends(get_current_user)):
    return current_user

@router.get("/role-test/merchant")
def test_merchant_only_endpoint(current_user: UserProfile = Depends(require_role(["merchant"]))):
    return {"message": "Access granted: Merchant Authorized", "user": current_user.email}

@router.get("/role-test/reviewer")
def test_reviewer_only_endpoint(current_user: UserProfile = Depends(require_role(["reviewer"]))):
    return {"message": "Access granted: Reviewer Authorized", "user": current_user.email}
