"""Application entrypoint: the webhook API and the dashboard, in one service."""

import logging
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import health, webhook
from app.auth import NotAuthenticated, NotAuthorised, login_redirect
from app.core.config import settings
from app.core.exceptions import WhatsAppBotException
from app.core.lifespan import lifespan
from app.middleware.logging import LoggingMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.web import register as register_web
from app.web import router as web_router

logger = logging.getLogger("app.main")

app = FastAPI(
    title=settings.app.name,
    version=settings.app.version,
    lifespan=lifespan,
    docs_url="/docs" if settings.app.environment == "development" else None,
    redoc_url=None,
)

# Middleware runs bottom-up: request ids are assigned before anything is logged.
app.add_middleware(LoggingMiddleware)
app.add_middleware(RequestIdMiddleware)

# Templates and the static mount.
register_web(app)

# Channel webhooks and health first, then the dashboard pages.
app.include_router(health.router, tags=["Health"])
app.include_router(webhook.router, tags=["WhatsApp Webhook"])
app.include_router(web_router, include_in_schema=False)


def _wants_html(request: Request) -> bool:
    """True when the caller is a browser rather than an API client."""
    return "text/html" in request.headers.get("accept", "")


def _error_page(request: Request, status: int, title: str, message: str) -> JSONResponse:
    """Renders an error as a page for browsers, JSON for everything else."""
    if not _wants_html(request):
        return JSONResponse(status_code=status, content={"error": title, "message": message})

    from app.web.templating import templates

    response = templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "app_name": settings.app.name,
            "year": datetime.now().year,
            "status": status,
            "title": title,
            "message": message,
        },
        status_code=status,
    )
    return response


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, exc: NotAuthenticated):
    """Sends a browser to the login page; answers API clients with 401."""
    if _wants_html(request):
        return login_redirect(exc.next_url)
    return JSONResponse(status_code=401, content={"error": "NotAuthenticated", "message": "Sign in required."})


@app.exception_handler(NotAuthorised)
async def not_authorised_handler(request: Request, exc: NotAuthorised):
    """Explains what the account cannot do rather than showing a blank 403."""
    logger.info(
        f"Access denied: {exc.message}",
        extra={"event": "access_denied", "path": request.url.path},
    )
    return _error_page(request, 403, "No access", exc.message)


@app.exception_handler(WhatsAppBotException)
async def whatsapp_bot_exception_handler(request: Request, exc: WhatsAppBotException):
    """Handles application errors: signature failures, missing records, API faults."""
    logger.error(
        f"Application error: {exc.message}",
        extra={
            "event": "app_custom_exception_handled",
            "status_code": exc.status_code,
            "error_detail": exc.message,
        },
    )
    if exc.status_code == 404:
        return _error_page(request, 404, "Not found", exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.__class__.__name__, "message": exc.message},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handles schema validation failures."""
    logger.error(
        f"Validation failure on {request.method} {request.url.path}",
        extra={"event": "request_validation_failed", "errors": exc.errors()},
    )
    return JSONResponse(status_code=422, content={"error": "ValidationError", "details": exc.errors()})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Last resort. Includes exception details in non-production environments."""
    logger.exception(
        f"Unhandled exception: {exc}",
        extra={"event": "unhandled_system_exception", "path": request.url.path},
    )
    detail = f"{type(exc).__name__}: {exc}" if settings.app.environment in ("development", "staging") or settings.app.debug else "An unexpected error occurred. The details are in the server log."
    return _error_page(
        request,
        500,
        "Something went wrong",
        detail,
    )
