"""Event handlers to process parsed webhook event inputs."""

import logging
from app.models.events import WhatsAppMessageReceivedEvent, WhatsAppStatusReceivedEvent
from app.services.interfaces.whatsapp import WhatsAppSenderInterface

logger = logging.getLogger("app.service.events.handlers")


async def log_message_handler(event: WhatsAppMessageReceivedEvent) -> None:
    """Logs the parsed incoming WhatsApp message detail."""
    message = event.message
    
    logger.info(
        f"Parsed incoming WhatsApp message from '{message.sender_name}' ({message.sender_id})",
        extra={
            "event": "whatsapp_message_parsed",
            "whatsapp_message_id": message.message_id,
            "sender": message.sender_id,
            "message_type": message.message_type,
            "content_length": len(message.content),
        }
    )


async def log_status_handler(event: WhatsAppStatusReceivedEvent) -> None:
    """Logs message status changes (e.g. delivered, read)."""
    status = event.status
    
    logger.info(
        f"Outbound message status update: message_id={status.id} status={status.status}",
        extra={
            "event": "whatsapp_status_update",
            "whatsapp_message_id": status.id,
            "sender": status.recipient_id,
            "message_status": status.status,
        }
    )


class AutoReplyHandler:
    """Testing handler that automatically echoes text messages back to the sender."""

    def __init__(self, sender: WhatsAppSenderInterface):
        """Initializes the auto-reply handler.

        Args:
            sender: Concrete implementation of WhatsAppSenderInterface.
        """
        self.sender = sender

    async def __call__(self, event: WhatsAppMessageReceivedEvent) -> None:
        message = event.message
        
        # Only echo text messages
        if message.message_type != "text":
            return

        text_body = message.content.strip()
        
        # Custom reply for testing
        if text_body.lower() == "ping":
            reply_text = "pong"
        else:
            reply_text = f"Echo: {text_body}"

        logger.info(
            f"Triggering auto-reply to {message.sender_id}",
            extra={
                "event": "whatsapp_auto_reply_triggered",
                "recipient": message.sender_id,
                "input": text_body
            }
        )

        try:
            # Dispatch text message via WhatsAppSender
            await self.sender.send_text(to=message.sender_id, text=reply_text)
            
            logger.info(
                f"Auto-reply sent to {message.sender_id}",
                extra={"event": "whatsapp_auto_reply_success", "recipient": message.sender_id}
            )
        except Exception as exc:
            logger.error(
                f"Failed to deliver auto-reply to {message.sender_id}: {exc}",
                extra={
                    "event": "whatsapp_auto_reply_failure",
                    "recipient": message.sender_id,
                    "error": str(exc)
                }
            )
