"""PDF report generator mirroring the DOCX template layout.

Text is written in full Unicode whenever a TrueType font is available (see
``app.reports.fonts``). Only when no such font is installed does the generator
fall back to Helvetica, and in that case ``_sanitise`` transliterates what it can
instead of dropping characters silently.
"""

import datetime
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.reports.fonts import FontSet, get_fonts

logger = logging.getLogger("app.reports.pdf_generator")

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

_HEADER_BG = (24, 43, 73)
_HEADER_FG = (255, 255, 255)
_TABLE_BG = (230, 240, 250)
_TABLE_ALT = (245, 248, 252)
_BORDER_CLR = (180, 190, 200)

# Replacements applied only in the Latin-1 fallback path.
_LATIN1_REPLACEMENTS = (
    ("✔", "v"), ("✖", "x"), ("✅", ""),
    ("⚠️", "[!]"), ("⚠", "[!]"),
    ("•", "-"), ("▸", ">"),
    ("■", "[x]"), ("□", "[ ]"),
    ("—", "-"), ("–", "-"),
    ("‘", "'"), ("’", "'"),
    ("“", '"'), ("”", '"'),
    ("₹", "INR "),
    ("\U0001f4cd", ""), ("\U0001f4c5", ""), ("\U0001f4dd", ""), ("\U0001f4f7", ""),
)


def _sanitise(text: Any, fonts: FontSet) -> str:
    """Prepares text for output.

    With a Unicode font registered this only normalises emoji that no report
    font carries. Without one it falls back to Latin-1 transliteration.
    """
    if text is None:
        return ""
    result = str(text)

    if fonts.unicode:
        # Emoji live outside every text font we ship; strip only those.
        return "".join(char for char in result if not _is_emoji(char))

    for old, new in _LATIN1_REPLACEMENTS:
        result = result.replace(old, new)
    return result.encode("latin-1", "replace").decode("latin-1")


def _is_emoji(char: str) -> bool:
    """True for pictographic code points that report fonts do not cover."""
    code = ord(char)
    return (
        0x1F300 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
        or code in (0xFE0F, 0x20E3)
    )


class PDFReportCompiler:
    """Builds a Daily Progress Report PDF matching the DOCX template layout."""

    def __init__(self, fonts: Optional[FontSet] = None):
        """Initializes the compiler.

        Args:
            fonts: Resolved font set. Discovered automatically when omitted.
        """
        from fpdf import FPDF

        self.FPDF = FPDF
        self.fonts = fonts or get_fonts()

    # --- text helpers ------------------------------------------------------

    def _t(self, value: Any) -> str:
        """Shorthand for sanitising a value against the active font set."""
        return _sanitise(value, self.fonts)

    def _font(self, pdf, style: str = "", size: float = 10) -> None:
        """Selects the resolved family at the requested style and size."""
        pdf.set_font(self.fonts.family, style, size)

    # --- public entry point ------------------------------------------------

    def create_pdf(
        self,
        draft_data: Dict[str, Any],
        photo_paths: Optional[List[str]],
        pdf_path: str,
    ) -> str:
        """Renders the report and writes it to ``pdf_path``.

        Args:
            draft_data: The extracted report dictionary.
            photo_paths: Local paths of photos to embed.
            pdf_path: Destination path.

        Returns:
            The path written.
        """
        pdf = self._new_document()

        report = _coerce_report(draft_data.get("report"))
        today = datetime.date.today()
        date_str = draft_data.get("date") or today.strftime("%Y-%m-%d")

        self._section_heading(pdf, "1. PROJECT INFORMATION")
        self._key_value_table(pdf, [
            ("Report Date", date_str),
            ("Project / Domain", _meta_value(report, "project_name", draft_data.get("site_name"))),
            ("Location / Department", _meta_value(report, "location", draft_data.get("site_name"))),
            ("Prepared By", _meta_value(report, "prepared_by", "Techknomatic AI Assistant")),
        ])
        pdf.ln(4)

        self._section_heading(pdf, "2. EXECUTIVE SUMMARY")
        self._font(pdf, "", 10)
        pdf.multi_cell(0, 6, self._t(draft_data.get("summary") or "Daily progress update recorded."))
        pdf.ln(4)

        self._render_work_summary(pdf, report, draft_data, date_str)
        self._render_resources(pdf, report)
        self._render_issues(pdf, report, draft_data)
        self._render_next_day_plan(pdf, report)
        self._render_overall_status(pdf, report)
        self._render_remarks(pdf, report)
        self._render_photographs(pdf, photo_paths)

        pdf.output(pdf_path)
        logger.info(
            f"PDF report generated at '{pdf_path}'.",
            extra={"event": "pdf_generated", "unicode_fonts": self.fonts.unicode},
        )
        return pdf_path

    # --- document scaffolding ---------------------------------------------

    def _new_document(self):
        """Creates the FPDF document with header, footer and fonts registered."""
        compiler = self

        class ReportPDF(self.FPDF):
            def header(self):
                compiler._font(self, "B", 16)
                self.set_text_color(*_HEADER_BG)
                self.cell(0, 10, compiler._t("TECHKNOMATIC"), new_x="LMARGIN", new_y="NEXT", align="C")
                compiler._font(self, "B", 11)
                self.cell(0, 7, compiler._t("DAILY PROJECT PROGRESS REPORT"), new_x="LMARGIN", new_y="NEXT", align="C")
                self.set_draw_color(*_HEADER_BG)
                self.set_line_width(0.6)
                self.line(10, self.get_y() + 1, 200, self.get_y() + 1)
                self.ln(4)

            def footer(self):
                self.set_y(-15)
                compiler._font(self, "I", 8)
                self.set_text_color(128, 128, 128)
                self.cell(
                    0, 10,
                    compiler._t(f"Page {self.page_no()} | Generated by Techknomatic AI Assistant"),
                    align="C",
                )

        pdf = ReportPDF()
        self.fonts.register(pdf)
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        return pdf

    # --- sections ----------------------------------------------------------

    def _render_work_summary(self, pdf, report, draft_data: Dict[str, Any], date_str: str) -> None:
        """Renders section 3, one row per activity."""
        self._section_heading(pdf, "3. WORK SUMMARY")

        items = list(report.work_summaries) if report else []
        if not items and draft_data.get("tasks"):
            from app.ai.schemas import WorkSummaryItem

            items = [WorkSummaryItem(activity=task) for task in draft_data["tasks"]]

        if not items:
            self._font(pdf, "I", 10)
            pdf.cell(0, 7, self._t("No specific work items recorded."), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
            return

        widths = [8, 25, 55, 10, 18, 20, 18, 36]
        self._table_header(pdf, ["#", "Area", "Activity", "%", "Date", "Person", "Status", "Remarks"], widths, 7)

        aligns = ["C", "L", "L", "C", "C", "L", "C", "L"]
        for index, item in enumerate(items):
            percentage = f"{item.progress_percentage}%" if item.progress_percentage is not None else ""
            item_date = item.date if item.date and item.date != "N/A" else date_str
            self._render_table_row(
                pdf,
                [str(index + 1), item.area, item.activity, percentage, item_date,
                 item.responsible_person, item.status, item.remarks],
                widths,
                fill=index % 2 == 1,
                alignments=aligns,
                font_size=6.5,
                line_height=3.2,
            )
        pdf.ln(4)

    def _render_resources(self, pdf, report) -> None:
        """Renders section 4."""
        self._section_heading(pdf, "4. RESOURCES USED")
        resources = list(report.resources) if report else []

        if not resources:
            self._font(pdf, "I", 10)
            pdf.cell(0, 7, self._t("No resource data recorded."), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
            return

        widths = [40, 100, 50]
        self._table_header(pdf, ["Type", "Description", "Quantity"], widths, 9)
        for index, resource in enumerate(resources):
            self._render_table_row(
                pdf,
                [resource.resource_type, resource.description, resource.quantity],
                widths,
                fill=index % 2 == 1,
                alignments=["L", "L", "C"],
                font_size=8,
                line_height=4.0,
            )
        pdf.ln(4)

    def _render_issues(self, pdf, report, draft_data: Dict[str, Any]) -> None:
        """Renders section 5, omitted entirely when there are no issues."""
        issues = list(report.issues) if report else []
        if not issues and draft_data.get("important_points"):
            from app.ai.schemas import IssueItem

            issues = [IssueItem(issue=point) for point in draft_data["important_points"]]

        if not issues:
            return

        self._section_heading(pdf, "5. ISSUES & HURDLES")
        widths = [55, 45, 45, 45]
        self._table_header(pdf, ["Issue", "Impact", "Action Taken", "Responsible"], widths, 9)
        for index, issue in enumerate(issues):
            self._render_table_row(
                pdf,
                [issue.issue, issue.impact, issue.action_taken, issue.responsible_person],
                widths,
                fill=index % 2 == 1,
                alignments=["L", "L", "L", "L"],
                font_size=8,
                line_height=4.0,
            )
        pdf.ln(4)

    def _render_next_day_plan(self, pdf, report) -> None:
        """Renders section 6, omitted when no plan was captured."""
        plans = list(report.next_day_plan) if report else []
        if not plans:
            return

        self._section_heading(pdf, "6. PLAN FOR NEXT DAY")
        widths = [45, 95, 50]
        self._table_header(pdf, ["Area", "Planned Activity", "Target Completion"], widths, 9)
        for index, plan in enumerate(plans):
            self._render_table_row(
                pdf,
                [plan.area, plan.planned_activity, plan.target_completion],
                widths,
                fill=index % 2 == 1,
                alignments=["L", "L", "C"],
                font_size=8,
                line_height=4.0,
            )
        pdf.ln(4)

    def _render_overall_status(self, pdf, report) -> None:
        """Renders section 7."""
        self._section_heading(pdf, "7. OVERALL PROJECT STATUS")
        percentage = report.overall_progress_percentage if report else None
        self._key_value_table(pdf, [
            ("Overall Progress", f"{percentage}%" if percentage is not None else "N/A"),
            ("Status", report.overall_status if report else "In Progress"),
        ])
        pdf.ln(4)

    def _render_remarks(self, pdf, report) -> None:
        """Renders section 8, omitted when there is nothing to say."""
        remarks = report.additional_remarks if report else "N/A"
        if not remarks or remarks == "N/A":
            return

        self._section_heading(pdf, "8. ADDITIONAL REMARKS")
        self._font(pdf, "", 10)
        pdf.multi_cell(0, 6, self._t(remarks))
        pdf.ln(4)

    def _render_photographs(self, pdf, photo_paths: Optional[List[str]]) -> None:
        """Renders section 9, embedding each photo that exists on disk."""
        self._section_heading(pdf, "9. PHOTOGRAPHS & ATTACHMENTS")
        valid = [p for p in (photo_paths or []) if p and os.path.exists(p)]

        if not valid:
            self._font(pdf, "I", 10)
            pdf.cell(0, 7, self._t("No photographs or attachments provided."), new_x="LMARGIN", new_y="NEXT")
            return

        for index, photo_path in enumerate(valid, 1):
            try:
                self._font(pdf, "B", 10)
                pdf.cell(0, 7, self._t(f"Photo {index}:"), new_x="LMARGIN", new_y="NEXT")
                pdf.image(photo_path, w=140)
                pdf.ln(4)
            except Exception as exc:
                logger.error(f"Could not embed photo {index} ('{photo_path}'): {exc}")

    # --- table primitives --------------------------------------------------

    def _table_header(self, pdf, headers: List[str], widths: List[float], font_size: float) -> None:
        """Draws a table header row."""
        self._font(pdf, "B", font_size)
        pdf.set_fill_color(*_TABLE_BG)
        pdf.set_draw_color(*_BORDER_CLR)
        for index, header in enumerate(headers):
            pdf.cell(widths[index], 7, self._t(header), border=1, fill=True, align="C")
        pdf.ln()

    def _render_table_row(
        self,
        pdf,
        values: List[Any],
        widths: List[float],
        fill: bool,
        alignments: Optional[List[str]] = None,
        font_size: float = 7.0,
        line_height: float = 3.5,
    ) -> None:
        """Draws one row, wrapping each cell and keeping the borders aligned."""
        aligns = alignments or ["C" if i == 0 else "L" for i in range(len(values))]
        self._font(pdf, "", font_size)
        pdf.set_draw_color(*_BORDER_CLR)

        # Measure first so every cell in the row shares one height.
        column_lines: List[List[str]] = []
        max_lines = 1
        for index, value in enumerate(values):
            lines = pdf.multi_cell(
                widths[index] - 2.0, line_height, self._t(value),
                dry_run=True, output="LINES",
            ) or [""]
            column_lines.append(list(lines))
            max_lines = max(max_lines, len(lines))

        row_height = max_lines * line_height + 3.0
        start_x, start_y = pdf.get_x(), pdf.get_y()

        if start_y + row_height > pdf.page_break_trigger:
            pdf.add_page()
            start_x, start_y = pdf.get_x(), pdf.get_y()

        cursor = start_x
        for index in range(len(values)):
            if fill:
                pdf.set_fill_color(*_TABLE_ALT)
                pdf.rect(cursor, start_y, widths[index], row_height, style="FD")
            else:
                pdf.rect(cursor, start_y, widths[index], row_height, style="D")
            cursor += widths[index]

        cursor = start_x
        for index, lines in enumerate(column_lines):
            align = aligns[index] if index < len(aligns) else "L"
            text_height = len(lines) * line_height
            pdf.set_xy(cursor + 1.0, start_y + (row_height - text_height) / 2.0)
            pdf.multi_cell(widths[index] - 2.0, line_height, "\n".join(lines), border=0, align=align)
            cursor += widths[index]

        pdf.set_xy(start_x, start_y + row_height)

    def _section_heading(self, pdf, title: str) -> None:
        """Draws a coloured section heading bar."""
        self._font(pdf, "B", 11)
        pdf.set_fill_color(*_HEADER_BG)
        pdf.set_text_color(*_HEADER_FG)
        pdf.set_draw_color(*_HEADER_BG)
        pdf.cell(0, 8, self._t(f"  {title}"), new_x="LMARGIN", new_y="NEXT", fill=True, border=1)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

    def _key_value_table(self, pdf, rows: List[tuple], col_widths=(50, 140)) -> None:
        """Draws a two-column label/value table."""
        pdf.set_draw_color(*_BORDER_CLR)
        for label, value in rows:
            self._font(pdf, "B", 10)
            pdf.set_fill_color(*_TABLE_BG)
            pdf.cell(col_widths[0], 7, self._t(f"  {label}"), border=1, fill=True)
            self._font(pdf, "", 10)
            pdf.cell(col_widths[1], 7, self._t(f"  {value}"), border=1)
            pdf.ln()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_report(report_obj: Any):
    """Normalises the ``report`` field into a ``FullProgressReport`` or ``None``."""
    if report_obj is None:
        return None
    if hasattr(report_obj, "metadata"):
        return report_obj
    if isinstance(report_obj, dict):
        from app.ai.schemas import FullProgressReport

        try:
            return FullProgressReport(**report_obj)
        except Exception as exc:
            logger.warning(f"Could not parse the report structure: {exc}")
    return None


def _meta_value(report, field: str, fallback: Any) -> str:
    """Reads a metadata field, preferring the report over the draft fallback."""
    if report is not None:
        value = getattr(report.metadata, field, None)
        if value and value != "N/A":
            return value
    return fallback or "N/A"


def convert_docx_to_pdf(docx_path: str, pdf_path: str) -> bool:
    """Converts a populated .docx to PDF using LibreOffice, if it is installed.

    Returns:
        True when a PDF was produced at ``pdf_path``.
    """
    soffice_bin = next(
        (
            path for path in (
                shutil.which("soffice"),
                shutil.which("libreoffice"),
                "/usr/bin/soffice",
                "/usr/bin/libreoffice",
                "/usr/local/bin/soffice",
            )
            if path and os.path.exists(path)
        ),
        None,
    )

    if not soffice_bin:
        logger.info("LibreOffice is not installed; using the native PDF renderer.")
        return False

    try:
        out_dir = os.path.dirname(pdf_path)
        result = subprocess.run(
            [soffice_bin, "--headless", "--convert-to", "pdf", docx_path, "--outdir", out_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        if result.returncode != 0:
            logger.warning(
                f"LibreOffice exited {result.returncode}: "
                f"{result.stderr.decode('utf-8', 'replace')[:500]}"
            )
            return False

        produced = os.path.join(out_dir, Path(docx_path).stem + ".pdf")
        if not os.path.exists(produced):
            logger.warning("LibreOffice reported success but produced no PDF.")
            return False

        if produced != pdf_path:
            shutil.move(produced, pdf_path)
        logger.info(f"Converted DOCX to PDF via LibreOffice: '{pdf_path}'.")
        return True
    except Exception as exc:
        logger.warning(f"LibreOffice conversion failed: {exc}")
        return False


def generate_native_pdf_report(
    draft_data: Dict[str, Any],
    photo_paths: Optional[List[str]],
    pdf_path: str,
) -> str:
    """Renders the report with fpdf2, matching the DOCX template layout."""
    return PDFReportCompiler().create_pdf(draft_data, photo_paths, pdf_path)
