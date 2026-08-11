"""Compact report preview message template."""

from typing import List, Optional
from datetime import datetime


def get_draft_preview(
    site_name: Optional[str],
    report_date: Optional[str],
    summary: Optional[str],
    work_completed: List[str],
    issues: List[str],
    photo_count: int,
) -> str:
    """Formats a compact structured report draft preview for WhatsApp review."""
    site = site_name or "Not specified"
    date_str = report_date or datetime.now().strftime("%d %b %Y")
    sum_str = summary or "No summary available."

    work_items = (
        "\n".join([f"• {item}" if not item.startswith("•") else item for item in work_completed])
        if work_completed
        else "• No tasks recorded"
    )
    
    issues_items = (
        "\n".join([f"• {item}" if not item.startswith("•") else item for item in issues])
        if issues
        else "• No issues reported"
    )

    return (
        "📝 *Report Draft*\n\n"
        "📍 *Project / Context:* " + f"{site}\n"
        "📅 *Date:* " + f"{date_str}\n\n"
        "📝 *Summary*\n"
        f"{sum_str}\n\n"
        "✅ *Work Completed*\n"
        f"{work_items}\n\n"
        "⚠️ *Issues*\n"
        f"{issues_items}\n\n"
        "📷 *Photos Attached:* " + f"{photo_count}\n\n"
        "Please review the draft before generating the final report."
    )
