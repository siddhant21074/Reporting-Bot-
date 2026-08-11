"""FastAPI dependency providers for the routing layer."""

import logging

from fastapi import Header, Request

from app.clients.whatsapp_client import WhatsAppClient
from app.core.config import settings
from app.core.exceptions import ConfigurationError, InvalidSignatureError
from app.core.security import verify_whatsapp_signature
from app.services.events.dispatcher import EventDispatcher
from app.services.whatsapp.receiver import WhatsAppReceiver
from app.services.whatsapp.sender import WhatsAppSender

logger = logging.getLogger("app.api.dependencies")


def get_whatsapp_client(request: Request) -> WhatsAppClient:
    """Injects the low-level WhatsApp HTTP client."""
    return request.app.state.whatsapp_client


def get_whatsapp_sender(request: Request) -> WhatsAppSender:
    """Injects the high-level message sending service."""
    return request.app.state.whatsapp_sender


def get_event_dispatcher(request: Request) -> EventDispatcher:
    """Injects the EventDispatcher service."""
    return request.app.state.event_dispatcher


def get_whatsapp_receiver(request: Request) -> WhatsAppReceiver:
    """Injects the webhook receiver coordinator."""
    return request.app.state.whatsapp_receiver


def get_ai_provider(request: Request):
    """Injects the configured AI provider."""
    return request.app.state.ai_provider


def get_session_store(request: Request):
    """Injects the session store."""
    return request.app.state.session_store


async def verify_signature_header(
    request: Request,
    x_hub_signature_256: str = Header(default="", alias="X-Hub-Signature-256"),
) -> None:
    """Rejects any webhook whose Meta signature does not verify.

    Raises:
        ConfigurationError: In production, when no app secret is configured.
        InvalidSignatureError: When the signature is absent or does not match.
    """
    secret = settings.whatsapp.app_secret

    if not secret:
        if settings.app.environment in ("development", "testing"):
            logger.warning(
                "WHATSAPP_APP_SECRET is not set — signature verification is skipped in "
                f"{settings.app.environment} mode only.",
                extra={"event": "signature_check_skipped"},
            )
            return
        # Never silently accept unauthenticated webhooks in production.
        logger.critical(
            "WHATSAPP_APP_SECRET is not configured; refusing to process the webhook.",
            extra={"event": "signature_check_unconfigured"},
        )
        raise ConfigurationError("WHATSAPP_APP_SECRET is not configured.")

    body = await request.body()
    if not verify_whatsapp_signature(body, x_hub_signature_256, secret):
        raise InvalidSignatureError()
