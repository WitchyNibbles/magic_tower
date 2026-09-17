from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .contracts import HealthResponse
from .config import get_settings
from .api.routes import router
from .api.auth import router as auth_router
from .api.sync import router as sync_router
from .api.session import router as session_router

app = FastAPI(title="Workboard API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.middleware("http")
async def add_local_security_headers_and_limit_json(request: Request, call_next):
    """Limit JSON before parsing and prevent browser/proxy persistence of PII."""
    if request.headers.get("content-type", "").split(";", 1)[0].lower() == "application/json":
        limit = get_settings().max_request_body_bytes
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > limit:
            return JSONResponse(
                status_code=413,
                content={"detail": "JSON request body is too large"},
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )
        # Content-Length is optional and can be dishonest. Starlette caches this
        # body, so downstream validation can still read it normally.
        if len(await request.body()) > limit:
            return JSONResponse(
                status_code=413,
                content={"detail": "JSON request body is too large"},
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Pragma", "no-cache")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    return response


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse()


app.include_router(router)
app.include_router(auth_router)
app.include_router(sync_router)
app.include_router(session_router)
