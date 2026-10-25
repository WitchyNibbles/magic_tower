import importlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import StatementError

from .contracts import HealthResponse
from .config import get_settings
from .services.field_crypto import FieldEncryptionError
from .services.scheduler import SyncScheduler, run_scheduled_sync
from .api.routes import router
from .api.auth import router as auth_router
from .api.sync import router as sync_router
from .api.session import router as session_router
from .api.grimoire import router as grimoire_router
from .api.projects import router as projects_router


APP_LOGGER_NAME = "app"
# Importing a connector's sync module is what registers its handler
# (``register_sync_handler``), and nothing else in the app calls into them, so they
# are imported by name here, once, when ``app.main`` is imported.
# ``tests/test_jira_sync.py`` / ``tests/test_freshservice_sync.py`` pin that this
# file alone is enough to register each kind.
SYNC_CONNECTOR_MODULE_NAMES = ("jira_sync", "freshservice_sync")
for _module_name in SYNC_CONNECTOR_MODULE_NAMES:
    importlib.import_module(f".services.{_module_name}", package=__package__)


def _configure_app_logging() -> None:
    """Make the app's own INFO lines (the scheduler's per-source results) visible.

    uvicorn configures only its own loggers; ``app.*`` propagates to a root logger
    with no handler and the default WARNING level, so INFO would be dropped. A
    handler and level on the ``app`` logger alone fixes that without touching the
    root logger or uvicorn's setup. It is skipped when something upstream already
    handles logging (a configured root logger), which also keeps repeated calls
    from stacking handlers.
    """
    app_logger = logging.getLogger(APP_LOGGER_NAME)
    if app_logger.hasHandlers():
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run the sync scheduler for as long as the app is up.

    Off when ``SYNC_INTERVAL_MINUTES`` is 0. The scheduler is stopped in a
    ``finally`` so a failing app still shuts its thread down.
    """
    _configure_app_logging()
    interval_minutes = get_settings().sync_interval_minutes
    scheduler: SyncScheduler | None = None
    if interval_minutes > 0:
        scheduler = SyncScheduler(interval_minutes * 60, run_scheduled_sync)
        scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.stop()


app = FastAPI(title="Magic Tower API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)


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


def _encryption_failure(error: BaseException) -> FieldEncryptionError | None:
    """The encryption failure behind ``error``, if that is what it is.

    SQLAlchemy raises the column type's error from inside a statement, so it
    arrives wrapped in a ``StatementError`` carrying the original on ``.orig``.
    """
    if isinstance(error, FieldEncryptionError):
        return error
    original = getattr(error, "orig", None)
    return original if isinstance(original, FieldEncryptionError) else None


@app.exception_handler(FieldEncryptionError)
@app.exception_handler(StatementError)
async def encrypted_content_unavailable(request: Request, error: Exception) -> JSONResponse:
    """Fail closed, like the other unusable-credential paths: 503, never cleartext.

    Reached when ``APP_ENCRYPTION_KEY`` is absent or does not open a stored excerpt.
    Both mean the deployment is misconfigured, not that the request was bad, and
    neither may be answered by writing or serving message content unencrypted. Any
    other statement failure is none of this handler's business and is re-raised.
    """
    failure = _encryption_failure(error)
    if failure is None:
        raise error
    return JSONResponse(status_code=503, content={"detail": str(failure)})


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse()


app.include_router(router)
app.include_router(auth_router)
app.include_router(sync_router)
app.include_router(session_router)
app.include_router(grimoire_router)
app.include_router(projects_router)
