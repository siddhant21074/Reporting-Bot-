"""Pydantic schemas for incoming Meta WhatsApp webhooks.

Meta delivers several unrelated event families on the same subscription --
messages, delivery statuses, template approvals, phone-number quality alerts and
account updates -- and the shape of ``value`` differs for each. Every field
below is therefore optional: the parser decides what it can handle, and anything
it cannot is dropped rather than rejected. A rejected delivery is retried with
backoff and eventually disables the webhook.
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Tolerant(BaseModel):
    """Base model that ignores fields Meta adds without warning."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Profile(_Tolerant):
    """Profile details of the message sender."""
    name: Optional[str] = None


class Contact(_Tolerant):
    """Contact associated with the webhook event."""
    profile: Optional[Profile] = None
    wa_id: Optional[str] = None


class Metadata(_Tolerant):
    """Metadata about the receiving business phone number."""
    display_phone_number: Optional[str] = None
    phone_number_id: Optional[str] = None


class TextMessage(_Tolerant):
    """Body of a text message."""
    body: Optional[str] = None


class MediaMessage(_Tolerant):
    """Media attachment: audio, voice, image, video or document."""
    id: Optional[str] = None
    mime_type: Optional[str] = None
    sha256: Optional[str] = None
    caption: Optional[str] = None
    filename: Optional[str] = None
    voice: Optional[bool] = None


class ButtonReply(_Tolerant):
    """Interactive button selection."""
    id: Optional[str] = None
    title: Optional[str] = None


class ListReply(_Tolerant):
    """Interactive list selection."""
    id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None


class InteractiveMessage(_Tolerant):
    """Interactive reply wrapping a button or list selection."""
    type: Optional[str] = None
    button_reply: Optional[ButtonReply] = None
    list_reply: Optional[ListReply] = None


class Message(_Tolerant):
    """An incoming message.

    ``id``, ``from`` and ``type`` are required: without them there is nothing to
    process, and a payload missing them is not a message payload.
    """
    from_number: str = Field(..., alias="from")
    id: str
    type: str
    timestamp: Optional[str] = None
    text: Optional[TextMessage] = None
    audio: Optional[MediaMessage] = None
    voice: Optional[MediaMessage] = None
    image: Optional[MediaMessage] = None
    document: Optional[MediaMessage] = None
    video: Optional[MediaMessage] = None
    sticker: Optional[MediaMessage] = None
    interactive: Optional[InteractiveMessage] = None


class StatusError(_Tolerant):
    """Error detail attached to a delivery status."""
    code: Optional[int] = None
    title: Optional[str] = None
    message: Optional[str] = None


class Status(_Tolerant):
    """Delivery status for an outbound message."""
    id: Optional[str] = None
    recipient_id: Optional[str] = None
    status: Optional[str] = None
    timestamp: Optional[str] = None
    errors: Optional[List[StatusError]] = None


class Value(_Tolerant):
    """Payload of a single change. Shape varies by ``Change.field``."""
    messaging_product: Optional[str] = None
    metadata: Optional[Metadata] = None
    contacts: Optional[List[Contact]] = None
    messages: Optional[List[Message]] = None
    statuses: Optional[List[Status]] = None
    errors: Optional[List[StatusError]] = None


class Change(_Tolerant):
    """A single change within an entry."""
    value: Value = Field(default_factory=Value)
    field: Optional[str] = None


class Entry(_Tolerant):
    """One entry of a webhook delivery."""
    id: Optional[str] = None
    changes: List[Change] = Field(default_factory=list)


class WebhookPayload(_Tolerant):
    """Root model for an incoming webhook POST."""
    object: Optional[str] = None
    entry: List[Entry] = Field(default_factory=list)
