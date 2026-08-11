"""Application-wide constants for SiteReport Bot."""

# WhatsApp Message Types
MESSAGE_TYPE_TEXT = "text"
MESSAGE_TYPE_AUDIO = "audio"
MESSAGE_TYPE_VOICE = "voice"
MESSAGE_TYPE_IMAGE = "image"
MESSAGE_TYPE_DOCUMENT = "document"
MESSAGE_TYPE_VIDEO = "video"
MESSAGE_TYPE_INTERACTIVE = "interactive"

# Set of message types parsed/supported by Phase 1
SUPPORTED_MESSAGE_TYPES = {
    MESSAGE_TYPE_TEXT,
    MESSAGE_TYPE_AUDIO,
    MESSAGE_TYPE_VOICE,
    MESSAGE_TYPE_IMAGE,
    MESSAGE_TYPE_DOCUMENT,
    MESSAGE_TYPE_VIDEO,
    MESSAGE_TYPE_INTERACTIVE,
}

# Meta API Graph Base URL
META_GRAPH_BASE_URL = "https://graph.facebook.com"

# Request Headers
HEADER_X_HUB_SIGNATURE = "X-Hub-Signature-256"
HEADER_X_REQUEST_ID = "X-Request-ID"
HEADER_CORRELATION_ID = "X-Correlation-ID"
