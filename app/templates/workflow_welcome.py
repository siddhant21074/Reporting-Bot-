"""Welcome message template for workflow conversation."""


def get_welcome_message() -> str:
    """Returns formatted welcome message greeting."""
    return (
        "👋 Welcome to *Techknomatic AI Report Assistant*!\n\n"
        "I'm here to help you generate professional *Daily Progress Reports*.\n\n"
        "Please choose how you would like to provide your report update:\n"
        "• Click 🎤 *Record Voice* to speak your update\n"
        "• Click 📝 *Text Update* to type your update"
    )
