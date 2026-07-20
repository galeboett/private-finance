from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from .api.accounts import router as accounts_router
from .api.aggregation import router as aggregation_router
from .api.auth import router as auth_router
from .api.categories import router as categories_router
from .api.imports import router as imports_router
from .api.networth import router as networth_router
from .api.operations import router as operations_router
from .api.pdf_templates import router as pdf_templates_router
from .api.rules import router as rules_router
from .api.review import router as review_router
from .api.settings import router as settings_router
from .api.transactions import router as transactions_router
from .bootstrap import initialize_database
from .config import settings
from .middleware import LocalhostSecurityMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["content-type", settings.csrf_header_name],
)
app.add_middleware(LocalhostSecurityMiddleware)
app.include_router(accounts_router)
app.include_router(aggregation_router)
app.include_router(auth_router)
app.include_router(categories_router)
app.include_router(imports_router)
app.include_router(networth_router)
app.include_router(operations_router)
app.include_router(pdf_templates_router)
app.include_router(rules_router)
app.include_router(review_router)
app.include_router(settings_router)
app.include_router(transactions_router)

@app.exception_handler(RequestValidationError)
async def sanitized_validation_error_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        errors.append(
            {
                "type": error.get("type"),
                "loc": error.get("loc"),
                "msg": error.get("msg"),
                "ctx": error.get("ctx"),
            }
        )
    return JSONResponse({"detail": errors}, status_code=422)


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
frontend_assets = frontend_dist / "assets"
if frontend_assets.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_assets)), name="assets")


@app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], include_in_schema=False)
def api_not_found(full_path: str):
    raise HTTPException(status_code=404, detail=f"API endpoint not found: /api/{full_path}")


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    index = frontend_dist / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return {"message": "Frontend not built yet", "path": full_path}
