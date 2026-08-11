"""Service for composing and dispatching messages via Meta WhatsApp API."""

from typing import Any, Dict, Optional
from app.services.interfaces.whatsapp import WhatsAppClientInterface, WhatsAppSenderInterface


class WhatsAppSender(WhatsAppSenderInterface):
    """High-level sender service that translates business needs into Meta payloads."""

    def __init__(self, client: WhatsAppClientInterface):
        """Initializes the sender service.

        Args:
            client: An implementation of WhatsAppClientInterface.
        """
        self.client = client

    async def send_text(self, to: str, text: str, preview_url: bool = False) -> Dict[str, Any]:
        """Composes and dispatches a plain text message to Meta API."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {
                "preview_url": preview_url,
                "body": text
            }
        }
        return await self.client.send_message_request(payload)

    async def send_document(
        self,
        to: str,
        media_id: Optional[str] = None,
        link: Optional[str] = None,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Composes and dispatches a document attachment message to Meta API.

        Args:
            to: Recipient phone number or wa_id.
            media_id: Meta media asset ID if pre-uploaded.
            link: Direct public HTTP/HTTPS URL if hosted online.
            filename: Attachment display filename.
            caption: Optional text caption.

        Returns:
            The Meta API JSON response dictionary.
        """
        doc_object: Dict[str, Any] = {}
        if media_id:
            doc_object["id"] = media_id
        elif link:
            doc_object["link"] = link
        else:
            raise ValueError("Either media_id or link must be provided to send a document.")

        if filename:
            doc_object["filename"] = filename
        if caption:
            doc_object["caption"] = caption

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "document",
            "document": doc_object,
        }
        return await self.client.send_message_request(payload)

    async def send_interactive_buttons(
        self,
        to: str,
        body_text: str,
        buttons: list,
        header_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Composes and dispatches interactive button reply message to Meta WhatsApp API."""
        button_actions = []
        for btn in buttons:
            button_actions.append({
                "type": "reply",
                "reply": {
                    "id": btn["id"],
                    "title": btn["title"][:20]  # Meta button title max 20 chars
                }
            })

        interactive_obj: Dict[str, Any] = {
            "type": "button",
            "body": {"text": body_text[:1000] if body_text else ""},
            "action": {"buttons": button_actions}
        }
        if header_text:
            interactive_obj["header"] = {"type": "text", "text": header_text}

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": interactive_obj
        }
        return await self.client.send_message_request(payload)
