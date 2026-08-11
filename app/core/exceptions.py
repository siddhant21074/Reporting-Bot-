"""Custom application-specific exceptions."""

class WhatsAppBotException(Exception):
    """Base exception class for all WhatsApp Bot application exceptions."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class WebhookVerificationError(WhatsAppBotException):
    """Exception raised when Meta webhook verification fails."""
    def __init__(self, message: str = "Webhook verify token mismatch"):
        super().__init__(message, status_code=403)


class InvalidSignatureError(WhatsAppBotException):
    """Exception raised when the X-Hub-Signature-256 header signature is invalid."""
    def __init__(self, message: str = "Invalid X-Hub-Signature-256 signature"):
        super().__init__(message, status_code=403)


class MetaAPIError(WhatsAppBotException):
    """Exception raised when calls to the Meta Cloud API fail."""
    def __init__(self, message: str, status_code: int = 502, details: str = ""):
        super().__init__(message, status_code)
        self.details = details


class ConfigurationError(WhatsAppBotException):
    """Exception raised when settings or keys are misconfigured."""
    def __init__(self, message: str):
        super().__init__(message, status_code=500)


class NotFoundError(WhatsAppBotException):
    """Exception raised when a requested resource does not exist."""
    def __init__(self, message: str = "Not found"):
        super().__init__(message, status_code=404)


class UnsupportedMessageType(WhatsAppBotException):
    """Exception raised when an unsupported media or interactive type is parsed."""
    def __init__(self, message: str):
        super().__init__(message, status_code=422)
