"""
Phase 15: Security Middleware & Rate Limiting Protections
=========================================================
Includes:
  1. SecurityHeadersMiddleware: Injects OWASP-recommended HTTP security headers
  2. Request payload size guardrail: Blocks requests exceeding MAX_CONTENT_LENGTH
  3. Sensitive endpoint rate limiting check
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from app.utils.security import execution_rate_limiter, sanitize_payload
from app.utils.logger import logger

MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 Megabytes ceiling

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Applies security headers to every HTTP response according to
    OWASP secure headers recommendations.
    """

    async def dispatch(self, request: Request, call_next):
        # 1. Check content-length ceiling to prevent memory denial-of-service
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_CONTENT_LENGTH:
                    return JSONResponse(
                        status_code=413,
                        content={"error": "PayloadTooLarge", "message": "Request payload exceeds maximum allowed size (2MB)."}
                    )
            except ValueError:
                pass

        # 2. Rate limiting check on sensitive execution endpoints
        if request.method == "POST" and ("/api/execution/execute" in request.url.path or "/api/recovery/batch/run" in request.url.path):
            client_ip = request.client.host if request.client else "unknown"
            if not execution_rate_limiter.is_allowed(client_ip):
                logger.warning(f"Security Rate limit triggered for IP {client_ip} on {request.url.path}")
                return JSONResponse(
                    status_code=429,
                    content={"error": "TooManyRequests", "message": "Rate limit exceeded on payment execution endpoint. Try again later."}
                )

        response: Response = await call_next(request)

        # 3. Inject OWASP Security Headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return response
