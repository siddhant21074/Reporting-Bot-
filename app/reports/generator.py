"""Document report generator module using python-docx to populate Daily Progress Report Word template."""

import os
import logging
import uuid
import datetime
import random
from pathlib import Path
from typing import Any, Dict, List, Optional
from docx import Document
from docx.shared import Inches
from app.core.config import settings
from app.ai.schemas import FullProgressReport

logger = logging.getLogger("app.reports.generator")


class DocxReportGenerator:
    """Generates official Word (.docx) Daily Progress Reports using python-docx matching Telegram template structure."""

    def __init__(self, reports_dir: Optional[str] = None, template_path: Optional[str] = None):
        """Initializes report generator.

        Args:
            reports_dir: Directory where generated reports are stored.
            template_path: Optional path to custom report_template.docx.
        """
        self.reports_dir = Path(reports_dir or settings.app.reports_dir)
        self.template_dir = Path("storage/templates")
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.template_dir.mkdir(parents=True, exist_ok=True)

        self.custom_template_path = Path(template_path) if template_path else None

    def _get_template_path(self) -> Path:
        if self.custom_template_path and self.custom_template_path.exists():
            return self.custom_template_path
        
        if self.template_dir.exists():
            for file_path in self.template_dir.glob("*.docx"):
                if not file_path.name.startswith("~$"):
                    return file_path
        
        # Fallback to default path
        return self.template_dir / "Daily_Project_Progress_Report_Template.docx"

    def generate_pdf_report(
        self,
        sender_id: str,
        draft: Dict[str, Any],
        photo_paths: Optional[List[str]] = None,
    ) -> str:
        """Generates a PDF report. First builds .docx then converts or compiles native PDF."""
        docx_path = self.generate_docx_report(sender_id, draft, photo_paths)
        pdf_path = docx_path.rsplit(".", 1)[0] + ".pdf"

        try:
            from app.reports.pdf_generator import convert_docx_to_pdf, generate_native_pdf_report

            if convert_docx_to_pdf(docx_path, pdf_path):
                return pdf_path

            return generate_native_pdf_report(draft, photo_paths, pdf_path)
        except Exception as exc:
            logger.error(f"PDF generation failed ({exc}). Falling back to DOCX: '{docx_path}'", exc_info=True)
            return docx_path

    def generate_report_by_format(
        self,
        sender_id: str,
        draft: Dict[str, Any],
        photo_paths: Optional[List[str]] = None,
        output_format: str = "pdf",
    ) -> str:
        """Generates report document in the specified format ('pdf' or 'docx')."""
        if (output_format or "").lower() == "pdf":
            return self.generate_pdf_report(sender_id, draft, photo_paths)
        return self.generate_docx_report(sender_id, draft, photo_paths)

    def generate_docx_report(
        self,
        sender_id: str,
        draft: Dict[str, Any],
        photo_paths: Optional[List[str]] = None,
    ) -> str:
        """Compiles structured output into official .docx file using Telegram populator logic."""
        template_path = self._get_template_path()
        if not template_path.exists():
            logger.error(f"Report template not found at: {template_path}")
            raise FileNotFoundError(f"Template document not found at {template_path.resolve()}")

        # Extract FullProgressReport object if available
        report_obj = draft.get("report")
        if isinstance(report_obj, dict):
            report_data = FullProgressReport(**report_obj)
        elif isinstance(report_obj, FullProgressReport):
            report_data = report_obj
        else:
            report_data = FullProgressReport()

        summary_text = draft.get("summary") or "Daily progress update recorded."
        
        # Convert string photo_paths to Path objects
        paths_list = [Path(p) for p in (photo_paths or []) if p and os.path.exists(p)]

        # Generate unique Report ID and filename
        today = datetime.date.today()
        today_str = today.strftime("%Y%m%d")
        random_suffix = random.randint(100, 999)
        report_id = f"RPT-{today_str}-{random_suffix}"
        
        filename = f"Daily_Report_{sender_id}_{report_id}.docx"
        output_path = self.reports_dir / filename

        # Open template
        doc = Document(template_path)
        tables = doc.tables
        num_tables = len(tables)
        logger.info(f"Loaded template with {num_tables} tables for {sender_id}.")

        # Table 2: Project Info (5 rows x 2 cols)
        if num_tables > 2:
            t = tables[2]
            try:
                t.cell(0, 1).text = report_id
                t.cell(1, 1).text = today.strftime("%Y-%m-%d")
                t.cell(2, 1).text = report_data.metadata.project_name if report_data.metadata.project_name != "N/A" else (draft.get("site_name") or "N/A")
                t.cell(3, 1).text = report_data.metadata.location if report_data.metadata.location != "N/A" else (draft.get("site_name") or "N/A")
                t.cell(4, 1).text = report_data.metadata.prepared_by if report_data.metadata.prepared_by != "N/A" else "Techknomatic AI Assistant"
                logger.info("Project Information (Table 2) populated.")
            except Exception as e:
                logger.error(f"Error populating Project Information: {e}")

        # Table 4: Executive Summary (1 row x 1 col)
        if num_tables > 4 and summary_text:
            t = tables[4]
            try:
                t.cell(0, 0).text = summary_text
                logger.info("Executive Summary (Table 4) populated.")
            except Exception as e:
                logger.error(f"Error populating Executive Summary: {e}")

        # Table 6: Work Summary (11 rows x 8 cols - header + 10 data rows)
        if num_tables > 6:
            t = tables[6]
            try:
                tasks_source = report_data.work_summaries
                if not tasks_source and draft.get("tasks"):
                    from app.ai.schemas import WorkSummaryItem
                    tasks_source = [WorkSummaryItem(activity=t) for t in draft.get("tasks", [])]

                for idx, item in enumerate(tasks_source):
                    row_idx = idx + 1
                    # The template ships a fixed number of blank rows; grow it
                    # rather than dropping the tasks that do not fit.
                    while len(t.rows) <= row_idx:
                        t.add_row()

                    t.cell(row_idx, 0).text = str(idx + 1)
                    t.cell(row_idx, 1).text = item.area
                    t.cell(row_idx, 2).text = item.activity
                    t.cell(row_idx, 3).text = f"{item.progress_percentage}%" if item.progress_percentage is not None else ""
                    t.cell(row_idx, 4).text = item.date if item.date != "N/A" else today.strftime("%Y-%m-%d")
                    t.cell(row_idx, 5).text = item.responsible_person
                    t.cell(row_idx, 6).text = item.status
                    t.cell(row_idx, 7).text = item.remarks

                # Trim only the rows left unused by this report.
                while len(t.rows) > len(tasks_source) + 1:
                    t._tbl.remove(t.rows[-1]._tr)

                logger.info(f"Work Summary (Table 6) populated with {len(tasks_source)} row(s).")
            except Exception as e:
                logger.error(f"Error populating Work Summary: {e}")

        # Table 8: Resources Used (4 rows x 3 cols)
        if num_tables > 8:
            t = tables[8]
            try:
                labour_desc, labour_qty = [], []
                equip_desc, equip_qty = [], []
                mat_desc, mat_qty = [], []

                for res in report_data.resources:
                    rt = res.resource_type.lower()
                    if any(k in rt for k in ["labour", "team", "man", "worker", "staff", "personnel", "human", "engineer", "dev"]):
                        labour_desc.append(res.description)
                        labour_qty.append(res.quantity)
                    elif any(k in rt for k in ["equipment", "tool", "equip", "hardware", "device", "server", "machine"]):
                        equip_desc.append(res.description)
                        equip_qty.append(res.quantity)
                    else:
                        mat_desc.append(res.description)
                        mat_qty.append(res.quantity)

                if labour_desc:
                    t.cell(1, 1).text = ", ".join(labour_desc)
                    t.cell(1, 2).text = ", ".join(labour_qty)
                if equip_desc:
                    t.cell(2, 1).text = ", ".join(equip_desc)
                    t.cell(2, 2).text = ", ".join(equip_qty)
                if mat_desc:
                    t.cell(3, 1).text = ", ".join(mat_desc)
                    t.cell(3, 2).text = ", ".join(mat_qty)
                logger.info("Resources Used (Table 8) populated.")
            except Exception as e:
                logger.error(f"Error populating Resources Used: {e}")

        # Table 10: Issues / Hurdles (4 cols)
        if num_tables > 10:
            t = tables[10]
            try:
                issues_source = report_data.issues
                if not issues_source and draft.get("important_points"):
                    from app.ai.schemas import IssueItem
                    issues_source = [IssueItem(issue=pt) for pt in draft.get("important_points", [])]

                for idx, issue in enumerate(issues_source):
                    if idx == 0:
                        t.cell(1, 0).text = issue.issue
                        t.cell(1, 1).text = issue.impact
                        t.cell(1, 2).text = issue.action_taken
                        t.cell(1, 3).text = issue.responsible_person
                    else:
                        row = t.add_row()
                        row.cells[0].text = issue.issue
                        row.cells[1].text = issue.impact
                        row.cells[2].text = issue.action_taken
                        row.cells[3].text = issue.responsible_person
                
                num_issues = len(issues_source)
                while len(t.rows) > num_issues + 1:
                    row_to_delete = t.rows[-1]
                    t._tbl.remove(row_to_delete._tr)

                logger.info("Issues / Hurdles (Table 10) populated.")
            except Exception as e:
                logger.error(f"Error populating Issues / Hurdles: {e}")

        # Table 12: Plan for Next Day (3 cols)
        if num_tables > 12:
            t = tables[12]
            try:
                for idx, plan in enumerate(report_data.next_day_plan):
                    if idx == 0:
                        t.cell(1, 0).text = plan.area
                        t.cell(1, 1).text = plan.planned_activity
                        t.cell(1, 2).text = plan.target_completion
                    else:
                        row = t.add_row()
                        row.cells[0].text = plan.area
                        row.cells[1].text = plan.planned_activity
                        row.cells[2].text = plan.target_completion
                
                num_plans = len(report_data.next_day_plan)
                while len(t.rows) > num_plans + 1:
                    row_to_delete = t.rows[-1]
                    t._tbl.remove(row_to_delete._tr)

                logger.info("Plan for Next Day (Table 12) populated.")
            except Exception as e:
                logger.error(f"Error populating Plan for Next Day: {e}")

        # Table 14: Overall Project Status (2 rows x 2 cols)
        if num_tables > 14:
            t = tables[14]
            try:
                pct = report_data.overall_progress_percentage
                pct_str = f"{pct}%" if pct is not None else "N/A"
                t.cell(1, 0).text = pct_str

                status = report_data.overall_status
                in_progress_cb = "■ In Progress" if status == "In Progress" else "□ In Progress"
                completed_cb = "■ Completed" if status == "Completed" else "□ Completed"
                delayed_cb = "■ Delayed" if status == "Delayed" else "□ Delayed"
                on_hold_cb = "■ On Hold" if status == "On Hold" else "□ On Hold"

                t.cell(1, 1).text = f"{in_progress_cb}    {completed_cb}    {delayed_cb}    {on_hold_cb}"
                logger.info("Overall Project Status (Table 14) populated.")
            except Exception as e:
                logger.error(f"Error populating Overall Project Status: {e}")

        # Table 18: Additional Remarks (1 row x 1 col)
        if num_tables > 18:
            t = tables[18]
            try:
                t.cell(0, 0).text = report_data.additional_remarks
                logger.info("Additional Remarks (Table 18) populated.")
            except Exception as e:
                logger.error(f"Error populating Additional Remarks: {e}")

        # Site Photographs section
        self._populate_site_photographs(doc, paths_list)

        # Save document
        doc.save(output_path)
        logger.info(f"Word report saved successfully to: {output_path}")
        return str(output_path)

    def _populate_site_photographs(self, doc: Document, photo_paths: List[Path]) -> None:
        """Populate the 'Site Photographs' section with photos or a placeholder message."""
        body = doc.element.body
        tables = doc.tables

        site_photos_table_idx = None
        for i, t in enumerate(tables):
            cell_text = t.cell(0, 0).text.strip().upper()
            if "SITE PHOTOGRAPHS" in cell_text:
                site_photos_table_idx = i
                break

        if site_photos_table_idx is None:
            logger.warning("'Site Photographs' section heading table not found. Skipping photo embedding.")
            return

        site_photos_heading_element = tables[site_photos_table_idx]._tbl

        # Clear only the placeholder paragraphs that belong to this section.
        # Removing everything up to sectPr also destroyed sign-off blocks and any
        # other content the template places after the photographs.
        elements_to_remove = []
        found_heading = False
        for child in list(body):
            tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if child is site_photos_heading_element:
                found_heading = True
                continue
            if not found_heading:
                continue
            if tag == 'sectPr':
                break
            if tag == 'tbl':
                # A following table starts the next section; stop here.
                break
            if tag == 'p' and not "".join(child.itertext()).strip():
                elements_to_remove.append(child)
                continue
            if tag == 'p':
                # A non-empty paragraph here is the template's placeholder text.
                elements_to_remove.append(child)
                continue
            break

        for elem in elements_to_remove:
            body.remove(elem)

        logger.info(
            f"Cleared {len(elements_to_remove)} placeholder paragraph(s) from the Site Photographs section."
        )

        insert_after = site_photos_heading_element

        if photo_paths:
            for idx, photo_path in enumerate(photo_paths):
                if not photo_path.exists():
                    logger.warning(f"Photo file not found, skipping: {photo_path}")
                    continue

                try:
                    caption_para = doc.add_paragraph()
                    caption_run = caption_para.add_run(f"▸  Photo {idx + 1}")
                    caption_run.bold = True
                    insert_after.addnext(caption_para._element)
                    insert_after = caption_para._element

                    photo_para = doc.add_paragraph()
                    run = photo_para.add_run()
                    run.add_picture(str(photo_path), width=Inches(4.5))
                    insert_after.addnext(photo_para._element)
                    insert_after = photo_para._element

                    spacer_para = doc.add_paragraph()
                    insert_after.addnext(spacer_para._element)
                    insert_after = spacer_para._element

                    logger.info(f"Embedded photo {idx + 1}: {photo_path.name}")
                except Exception as e:
                    logger.error(f"Failed to embed photo {idx + 1} ({photo_path}): {e}")
        else:
            no_photo_para = doc.add_paragraph()
            no_photo_para.text = "No photographs provided."
            insert_after.addnext(no_photo_para._element)
            logger.info("No photographs provided — placeholder text inserted.")
