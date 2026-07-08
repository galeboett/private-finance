from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import settings


class LocalhostSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host and host not in settings.allowed_hosts:
            return JSONResponse({"detail": "Invalid host"}, status_code=403)

        origin = request.headers.get("origin")
        if origin and origin not in settings.allowed_origins:
            return JSONResponse({"detail": "Invalid origin"}, status_code=403)

        return await call_next(request)

