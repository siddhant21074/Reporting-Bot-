"""Receiver service coordinating webhook parsing and background event dispatching."""

import logging
from fastapi import BackgroundTasks

from app.models.events import WhatsAppMessageReceivedEvent, WhatsAppStatusReceivedEvent
from app.schemas.webhook import WebhookPayload
from app.services.events.dispatcher import EventDispatcher
from app.services.whatsapp.parser import WhatsAppParser

logger = logging.getLogger("app.service.whatsapp.receiver")


class WhatsAppReceiver:
    """Service responsible for webhook payloads orchestration."""

    def __init__(self, parser: WhatsAppParser, dispatcher: EventDispatcher):
        """Initializes the webhook receiver.

        Args:
            parser: The WhatsApp parser service.
            dispatcher: The EventDispatcher service.
        """
        self.parser = parser
        self.dispatcher = dispatcher

    async def receive_webhook(self, payload: WebhookPayload, background_tasks: BackgroundTasks) -> None:
        """Parses webhook messages and statuses, queuing them as background dispatch tasks.

        Args:
            payload: WebhookPayload object from Meta.
            background_tasks: FastAPI background execution context.
        """
        logger.info(
            "Receiving Meta webhook payload.",
            extra={"event": "webhook_received", "payload_object": payload.object}
        )

        # 1. Parse and dispatch incoming messages
        try:
            parsed_messages = self.parser.parse_payload(payload)
            for message in parsed_messages:
                event = WhatsAppMessageReceivedEvent(message=message)
                
                # Defer the handler execution to FastAPI background tasks
                background_tasks.add_task(self.dispatcher.dispatch, event)
                
                logger.info(
                    f"Scheduled background dispatch for message {message.message_id}",
                    extra={
                        "event": "message_event_queued",
                        "whatsapp_message_id": message.message_id,
                        "event_id": event.event_id
                    }
                )
        except Exception as exc:
            logger.exception(
                f"Exception encountered during message event extraction: {exc}",
                extra={"event": "webhook_message_processing_failed", "error": str(exc)}
            )

        # 2. Parse and dispatch message delivery status changes (sent, delivered, read, failed)
        try:
            for entry in payload.entry:
                for change in entry.changes:
                    if change.value.statuses:
                        for status in change.value.statuses:
                            event = WhatsAppStatusReceivedEvent(status=status)
                            
                            # Defer delivery statuses to background tasks
                            background_tasks.add_task(self.dispatcher.dispatch, event)

                            logger.info(
                                f"Scheduled background dispatch for status {status.id} ({status.status})",
                                extra={
                                    "event": "status_event_queued",
                                    "whatsapp_message_id": status.id,
                                    "event_id": event.event_id
                                }
                            )
        except Exception as exc:
            logger.exception(
                f"Exception encountered during status event extraction: {exc}",
                extra={"event": "webhook_status_processing_failed", "error": str(exc)}
            )
