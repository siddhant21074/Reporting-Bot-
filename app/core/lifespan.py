"""Application lifespan management."""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, List

import httpx
from fastapi import FastAPI

from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.core.logger import setup_logging

logger = logging.getLogger("app.lifespan")

# How often expired sessions are swept out of memory.
SESSION_SWEEP_INTERVAL_SECONDS = 300

# How often expired messages, reports and media are purged.
RETENTION_SWEEP_INTERVAL_SECONDS = 3600


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Wires services on startup and tears them down cleanly on shutdown."""
    setup_logging(settings.app.log_level)
    app.state.start_time = time.time()

    app_settings = settings.app
    _ensure_storage_directories(app_settings)

    # The database comes up before configuration is validated: settings saved
    # from the dashboard are layered over .env, so a credential set in the UI
    # must be visible to the check that follows.
    from app.db.base import init_database
    from app.repositories import settings_store

    await init_database()

    from app.db.base import session_scope

    async with session_scope() as session:
        await settings_store.load_overrides(session)
        await session.commit()

    _validate_configuration()

    logger.info(
        "Application starting up...",
        extra={
            "event": "app_startup_begin",
            "app_name": app_settings.name,
            "app_version": app_settings.version,
            "environment": app_settings.environment,
        },
    )

    # --- HTTP connection pool for outbound channel and provider calls ------
    http_client = httpx.AsyncClient(
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
        timeout=httpx.Timeout(float(app_settings.http_timeout), connect=5.0),
        follow_redirects=True,
    )
    app.state.http_client = http_client
    logger.info("HTTP client pool initialized.", extra={"event": "http_client_initialized"})

    # --- Domain wiring ----------------------------------------------------
    from app.ai import AIProvider
    from app.clients.whatsapp_client import WhatsAppClient
    from app.reports.generator import DocxReportGenerator
    from app.services.events.dispatcher import EventDispatcher
    from app.services.events.handlers import log_message_handler, log_status_handler
    from app.services.events.report_handler import ReportSessionHandler
    from app.services.whatsapp.media import WhatsAppMediaDownloader
    from app.services.whatsapp.parser import WhatsAppParser
    from app.services.whatsapp.receiver import WhatsAppReceiver
    from app.services.whatsapp.sender import WhatsAppSender
    from app.services.workflow.engine import ConversationEngine
    from app.sessions import SessionStore

    whatsapp_client = WhatsAppClient(http_client)
    whatsapp_sender = WhatsAppSender(whatsapp_client)
    whatsapp_parser = WhatsAppParser()
    whatsapp_media_downloader = WhatsAppMediaDownloader(whatsapp_client)
    event_dispatcher = EventDispatcher()

    session_store = SessionStore(timeout_seconds=app_settings.session_timeout_seconds)

    # The provider reads settings lazily, so a Settings-page change takes effect
    # without a restart. A missing key surfaces on first use, not at boot.
    ai_provider = AIProvider()
    logger.info(
        "AI provider configured.",
        extra={"event": "ai_provider_configured", **_flatten(ai_provider.describe())},
    )

    conversation_engine = ConversationEngine(docx_generator=DocxReportGenerator())

    report_handler = ReportSessionHandler(
        sender=whatsapp_sender,
        session_store=session_store,
        ai_provider=ai_provider,
        media_downloader=whatsapp_media_downloader,
        engine=conversation_engine,
    )

    event_dispatcher.register("whatsapp.message_received", log_message_handler)
    event_dispatcher.register("whatsapp.status_received", log_status_handler)
    event_dispatcher.register("whatsapp.message_received", report_handler)

    app.state.whatsapp_client = whatsapp_client
    app.state.whatsapp_sender = whatsapp_sender
    app.state.session_store = session_store
    app.state.ai_provider = ai_provider
    app.state.event_dispatcher = event_dispatcher
    app.state.whatsapp_receiver = WhatsAppReceiver(whatsapp_parser, event_dispatcher)

    logger.info("Services wired successfully.", extra={"event": "services_wire_complete"})

    # --- Background maintenance ------------------------------------------
    app.state.last_purge_at = None
    background_tasks: List[asyncio.Task] = [
        asyncio.create_task(_sweep_sessions(session_store), name="session-sweeper"),
        asyncio.create_task(_sweep_retention(app), name="retention-sweeper"),
    ]
    app.state.background_tasks = background_tasks

    yield

    # --- Shutdown ---------------------------------------------------------
    logger.info("Application shutting down...", extra={"event": "app_shutdown_begin"})

    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)

    from app.db.base import close_database

    await close_database()
    await http_client.aclose()
    logger.info("HTTP client pool closed.", extra={"event": "http_client_closed"})
    logger.info("Application shutdown complete.", extra={"event": "app_shutdown_complete"})


def _validate_configuration() -> None:
    """Checks that at least one channel is usable, and that production is locked down.

    Raises:
        ConfigurationError: If a production deployment is missing required values.
    """
    problems: List[str] = []
    warnings: List[str] = []
    is_production = settings.app.environment not in ("testing", "development")

    whatsapp = settings.whatsapp
    telegram = settings.telegram

    if whatsapp.enabled and not whatsapp.is_configured:
        missing = [
            name for name, value in (
                ("WHATSAPP_ACCESS_TOKEN", whatsapp.access_token),
                ("WHATSAPP_PHONE_NUMBER_ID", whatsapp.phone_number_id),
                ("WHATSAPP_VERIFY_TOKEN", whatsapp.verify_token),
                ("WHATSAPP_APP_SECRET", whatsapp.app_secret),
            ) if not value
        ]
        warnings.append(f"WhatsApp channel enabled but incomplete: {', '.join(missing)}")

    if telegram.enabled and not telegram.is_configured:
        warnings.append("Telegram channel enabled but TELEGRAM_BOT_TOKEN is not set")

    if not whatsapp.is_configured and not telegram.is_configured:
        warnings.append("No channel is fully configured — the bot cannot send or receive yet")

    if not settings.llm.is_configured:
        warnings.append(
            f"LLM provider '{settings.llm.provider}' has no API key; "
            "reports will fall back to rule-based structuring"
        )
    if not settings.stt.is_configured:
        from app.ai.registry import detect_local_stt, local_stt_label

        if detect_local_stt():
            warnings.append(
                f"Speech-to-text provider '{settings.stt.provider}' has no API key; "
                f"falling back to the built-in engine ({local_stt_label()}), "
                "which is less accurate"
            )
        else:
            warnings.append(
                f"Speech-to-text provider '{settings.stt.provider}' has no API key and "
                "no built-in engine is installed; voice notes will not transcribe. "
                "Add a key, or run: pip install faster-whisper"
            )

    if is_production:
        # A blank app secret used to silently disable signature verification.
        if whatsapp.enabled and not whatsapp.app_secret:
            problems.append("WHATSAPP_APP_SECRET is required in production — it authenticates Meta's webhooks")
        if not settings.admin.secret_key:
            problems.append("SECRET_KEY is required in production — it signs admin session cookies")

    if problems:
        message = f"Invalid configuration for environment '{settings.app.environment}': " + "; ".join(problems)
        logger.critical(message, extra={"event": "startup_configuration_failed", "problems": problems})
        raise ConfigurationError(message)

    for warning in warnings:
        logger.warning(warning, extra={"event": "startup_configuration_warning"})


def _ensure_storage_directories(app_settings) -> None:
    """Creates the storage directories the app writes into."""
    for directory in (
        app_settings.logs_dir,
        app_settings.media_dir,
        app_settings.reports_dir,
        app_settings.temp_dir,
        app_settings.fonts_dir,
    ):
        if directory:
            os.makedirs(directory, exist_ok=True)


async def _sweep_sessions(session_store) -> None:
    """Periodically purges expired sessions so memory does not grow unbounded."""
    while True:
        try:
            await asyncio.sleep(SESSION_SWEEP_INTERVAL_SECONDS)
            removed = await session_store.clear_expired_sessions()
            if removed:
                logger.info(
                    f"Swept {removed} expired session(s).",
                    extra={"event": "session_sweep", "removed": removed},
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"Session sweep failed: {exc}", exc_info=True)


async def _sweep_retention(app: FastAPI) -> None:
    """Deletes messages, reports and media past the retention window.

    Runs once shortly after startup so a deployment that has been down for a
    while catches up, then hourly.
    """
    from app.db.base import session_scope
    from app.repositories import history

    await asyncio.sleep(30)

    while True:
        try:
            async with session_scope() as session:
                removed = await history.purge_expired(session)
                await session.commit()

            orphans = await asyncio.to_thread(history.purge_orphan_files)
            if orphans:
                logger.info(
                    f"Removed {orphans} orphaned file(s) past the retention window.",
                    extra={"event": "retention_orphans", "files": orphans},
                )

            from app.db.models import utcnow

            app.state.last_purge_at = utcnow().strftime("%d %b %Y, %H:%M UTC")
            _ = removed

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"Retention sweep failed: {exc}", exc_info=True)

        await asyncio.sleep(RETENTION_SWEEP_INTERVAL_SECONDS)


def _flatten(described: dict) -> dict:
    """Flattens the AI provider description for structured log output."""
    return {
        "chat_provider": described["chat"]["provider"],
        "chat_model": described["chat"]["model"],
        "stt_provider": described["stt"]["provider"],
        "stt_model": described["stt"]["model"],
    }
