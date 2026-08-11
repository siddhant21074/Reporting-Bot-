"""Report completion and document delivery templates."""

from typing import Optional


def get_report_generated_ack(report_title: Optional[str] = None) -> str:
    """Returns confirmation message upon report generation."""
    return (
        "🎉 Report Generated Successfully!\n\n"
        "Your report is ready."
    )
