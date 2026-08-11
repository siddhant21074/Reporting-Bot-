"""Workflow reset notification template."""


def get_workflow_reset_ack() -> str:
    """Returns reset confirmation message."""
    return (
        "🔄 Conversation, voice notes, photos, and report buffer reset.\n\n"
        "Send any message or voice note to begin a new report."
    )
