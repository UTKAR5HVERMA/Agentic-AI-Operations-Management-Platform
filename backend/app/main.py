"""FastAPI app: lifespan (schema + seed + scheduler), middleware, error format, routers, SPA."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import logging_config, scheduler
from app.config import get_settings
from app.context import client_ip_var, request_id_var
from app.db import Base, SessionLocal, add_missing_columns, get_engine
from app.errors import ApiError
from app.routers import admin, approvals, audit, auth, communications, reports, requests, simulate
from app.seed import seed_if_empty, sync_demo_users

log = logging.getLogger("app")
STATIC_DIR = Path(__file__).parent / "static"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging_config.configure(settings.log_level)
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    if added := add_missing_columns(engine):
        log.info("db.columns_added", extra={"columns": added})
    if settings.seed_on_startup:
        with SessionLocal() as db:
            if seed_if_empty(db):
                log.info("seed.completed")
            elif synced := sync_demo_users(db):
                log.info("seed.demo_users_synced", extra={"count": len(synced)})
    task = asyncio.create_task(scheduler.run_forever()) if settings.scheduler_enabled else None
    log.info(
        "startup", extra={"llm_mode": settings.llm_mode, "llm_configured": settings.llm_configured}
    )
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="OpsPilot API",
        version="1.0.0",
        lifespan=lifespan,
        description="Agentic AI Operations Assistant — LLMs propose, policy decides.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(_request_context)
    _register_error_handlers(app)
    for module in (auth, requests, approvals, communications, reports, audit, admin, simulate):
        app.include_router(module.router, prefix="/api")
    _mount_frontend(app)
    return app


async def _request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    request_id_var.set(rid)
    client_ip_var.set(request.client.host if request.client else None)
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    log.info(
        "http.request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": int((time.perf_counter() - started) * 1000),
        },
    )
    return response


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            {"detail": exc.detail, "code": exc.code},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {"detail": exc.detail, "code": f"HTTP_{exc.status_code}"}, status_code=exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        return JSONResponse(
            {
                "detail": f"{where}: {first.get('msg', 'invalid input')}",
                "code": "VALIDATION_ERROR",
                "errors": jsonable_encoder(exc.errors()),
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error")
        return JSONResponse(
            {"detail": "Unexpected server error", "code": "INTERNAL_ERROR"}, status_code=500
        )


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built React app with SPA fallback (non-/api paths → index.html)."""
    if not (STATIC_DIR / "index.html").exists():
        return
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise ApiError(404, "NOT_FOUND", "Not found")
        candidate = STATIC_DIR / path
        if path and candidate.is_file() and STATIC_DIR in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")


app = create_app()
