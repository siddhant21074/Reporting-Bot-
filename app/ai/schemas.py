"""Pydantic schemas for structured AI report extraction matching Telegram bot schema and WhatsApp bot requirements."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    """Overall project progress health status."""
    ON_TRACK = "On Track"
    DELAYED = "Delayed"
    BLOCKED = "Blocked"
    UNKNOWN = "Unknown"


class ReportMetadata(BaseModel):
    """Metadata fields located in Table 2 (Project Information) of the template."""
    project_name: Optional[str] = Field(default="N/A", description="Name of project, domain, or team. Default is 'N/A' if not mentioned.")
    location: Optional[str] = Field(default="N/A", description="Location, site, module, or department name. Default is 'N/A' if not mentioned.")
    prepared_by: Optional[str] = Field(default="N/A", description="Name of the person who spoke or prepared this update. Default is 'N/A' if not mentioned.")


class WorkSummaryItem(BaseModel):
    """Individual row item for Table 6 (Work Summary) in the template."""
    area: Optional[str] = Field(default="N/A", description="Area, module, feature, or department of this specific activity.")
    activity: Optional[str] = Field(default="N/A", description="Details of the work or activity completed/ongoing.")
    progress_percentage: Optional[int] = Field(default=None, description="Progress percentage integer for this activity (0-100), or null.")
    date: Optional[str] = Field(default="N/A", description="Date of the activity. Default is 'N/A'.")
    responsible_person: Optional[str] = Field(default="N/A", description="Responsible person for this specific work.")
    status: Optional[str] = Field(default="In Progress", description="Status must be one of: 'In Progress', 'Completed', 'Delayed', 'On Hold'.")
    remarks: Optional[str] = Field(default="N/A", description="Additional remarks or notes for this activity.")


class ResourceItem(BaseModel):
    """Individual resource item for Table 8 (Resources Used) in the template."""
    resource_type: Optional[str] = Field(default="Team/Labour", description="Resource category e.g. 'Team/Labour', 'Equipment/Tools', 'Material/Software/Resources'.")
    description: Optional[str] = Field(default="", description="Description of resources (e.g. '3 Engineers', 'Server Instance', 'Cement bags', 'Salesforce License').")
    quantity: Optional[str] = Field(default="", description="Quantity or metrics (e.g., '3', '1 unit', '8 hours').")


class IssueItem(BaseModel):
    """Individual issue row for Table 10 (Issues / Hurdles) in the template."""
    issue: Optional[str] = Field(default="", description="Details of the blocker or issue encountered. Leave blank if none.")
    impact: Optional[str] = Field(default="", description="Impact of the issue on schedule or progress. Leave blank if none.")
    action_taken: Optional[str] = Field(default="", description="Action taken to address or resolve. Leave blank if none.")
    responsible_person: Optional[str] = Field(default="", description="Responsible person for resolving the issue. Leave blank if none.")


class NextDayPlanItem(BaseModel):
    """Individual plan row for Table 12 (Plan for Next Day) in the template."""
    area: Optional[str] = Field(default="N/A", description="Tomorrow's work area or location.")
    planned_activity: Optional[str] = Field(default="N/A", description="Planned work or targets for tomorrow.")
    target_completion: Optional[str] = Field(default="N/A", description="Target completion timeline.")


class FullProgressReport(BaseModel):
    """Full progress report structure mapping the multi-table template."""
    metadata: ReportMetadata = Field(default_factory=ReportMetadata)
    work_summaries: List[WorkSummaryItem] = Field(default_factory=list, description="List of work summaries. Extract up to 10 entries.")
    resources: List[ResourceItem] = Field(default_factory=list, description="List of resources used.")
    issues: List[IssueItem] = Field(default_factory=list, description="List of issues or hurdles encountered.")
    next_day_plan: List[NextDayPlanItem] = Field(default_factory=list, description="List of plan items for the next day.")
    overall_progress_percentage: Optional[int] = Field(default=None, description="Overall progress percentage integer (0-100).")
    overall_status: str = Field(default="In Progress", description="Overall project status: 'In Progress', 'Completed', 'Delayed', 'On Hold'.")
    additional_remarks: str = Field(default="N/A", description="General remarks placed at the bottom under 'Additional Remarks'.")


class ExtractedReport(BaseModel):
    """Structured report format turning transcript into structured output compatible with WhatsApp bot."""
    site_name: Optional[str] = Field(default=None, description="Name of project, site, or location")
    report_date: Optional[str] = Field(default=None, description="Date of report")
    reporter_name: Optional[str] = Field(default=None, description="Name or role of person submitting report")
    
    summary: Optional[str] = Field(default=None, description="Executive summary of daily progress")
    tasks: List[str] = Field(default_factory=list, description="List of tasks and work completed today")
    important_points: List[str] = Field(default_factory=list, description="Key highlights, safety incidents, or important points")
    report_content: Optional[str] = Field(default=None, description="Detailed report content body and issue details")
    
    # Detailed Telegram template schema
    report: Optional[FullProgressReport] = Field(default=None, description="Full progress report template model")
    
    work_completed: List[str] = Field(default_factory=list, description="Tasks completed list")
    issues_and_blockers: List[str] = Field(default_factory=list, description="List of issues or blockers")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Key metrics")
    project_status: ProjectStatus = Field(default=ProjectStatus.UNKNOWN, description="Project status")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Extraction confidence score")

    def merge_with(self, newer: "ExtractedReport") -> "ExtractedReport":
        """Merges a newer extraction update into the current report draft."""
        merged_site = newer.site_name or self.site_name
        merged_date = newer.report_date or self.report_date
        merged_reporter = newer.reporter_name or self.reporter_name
        
        merged_summary = newer.summary if newer.summary else self.summary
        merged_content = newer.report_content if newer.report_content else self.report_content
        merged_report = newer.report if newer.report else self.report

        all_tasks = list(dict.fromkeys(self.tasks + newer.tasks + self.work_completed + newer.work_completed))
        all_points = list(dict.fromkeys(self.important_points + newer.important_points + self.issues_and_blockers + newer.issues_and_blockers))

        merged_metrics = {**self.metrics, **newer.metrics}
        merged_status = (
            newer.project_status
            if newer.project_status != ProjectStatus.UNKNOWN
            else self.project_status
        )

        return ExtractedReport(
            site_name=merged_site,
            report_date=merged_date,
            reporter_name=merged_reporter,
            summary=merged_summary,
            tasks=all_tasks,
            important_points=all_points,
            report_content=merged_content,
            report=merged_report,
            work_completed=all_tasks,
            issues_and_blockers=all_points,
            metrics=merged_metrics,
            project_status=merged_status,
            confidence_score=min(self.confidence_score, newer.confidence_score),
        )
