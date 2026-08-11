"""Conversation Engine orchestrating workflow state transitions."""

import logging
from typing import Dict, Optional

from app.sessions.models import UserSession, WorkflowState
from app.models.whatsapp import ParsedMessage
from app.ai.provider import AIProviderInterface
from app.services.whatsapp.media import WhatsAppMediaDownloader
from app.reports.generator import DocxReportGenerator
from app.services.workflow.states import (
    WorkflowContext,
    WorkflowStateBase,
    IdleState,
    WaitingForInputState,
    WaitingForPhotosState,
    WaitingForConfirmationState,
    GeneratingReportState,
    ReportGeneratedState,
    CancelledState,
)

logger = logging.getLogger("app.services.workflow.engine")


class ConversationEngine:
    """State machine orchestrator for workflow-driven report generation."""

    def __init__(self, docx_generator: Optional[DocxReportGenerator] = None):
        """Initializes the conversation engine and state handler lookup table."""
        self.docx_generator = docx_generator or DocxReportGenerator()
        self._state_handlers: Dict[WorkflowState, WorkflowStateBase] = {
            WorkflowState.IDLE: IdleState(),
            WorkflowState.WAITING_FOR_INPUT: WaitingForInputState(),
            WorkflowState.WAITING_FOR_PHOTOS: WaitingForPhotosState(),
            WorkflowState.WAITING_FOR_CONFIRMATION: WaitingForConfirmationState(),
            WorkflowState.GENERATING_REPORT: GeneratingReportState(),
            WorkflowState.REPORT_GENERATED: ReportGeneratedState(),
            WorkflowState.CANCELLED: CancelledState(),
        }

    async def process_message(
        self,
        session: UserSession,
        message: ParsedMessage,
        ai_provider: AIProviderInterface,
        media_downloader: Optional[WhatsAppMediaDownloader] = None,
    ) -> str:
        """Processes incoming message through current workflow state handler.

        Args:
            session: Active user conversation session.
            message: Parsed WhatsApp incoming message.
            ai_provider: AI processing engine implementation.
            media_downloader: Optional media downloader service.

        Returns:
            The response string to send to the WhatsApp user.
        """
        ctx = WorkflowContext(
            session=session,
            message=message,
            ai_provider=ai_provider,
            media_downloader=media_downloader,
            docx_generator=self.docx_generator,
        )

        current_state = session.state
        handler = self._state_handlers.get(current_state, IdleState())

        logger.info(
            f"Orchestrating message from {message.sender_id} in state '{current_state.value}' via {handler.__class__.__name__}",
            extra={
                "event": "workflow_state_execution",
                "sender_id": message.sender_id,
                "current_state": current_state.value,
                "message_type": message.message_type,
            }
        )

        reply_text = await handler.handle_message(ctx)

        logger.info(
            f"State execution complete. New state='{session.state.value}' for {message.sender_id}",
            extra={
                "event": "workflow_state_transition",
                "sender_id": message.sender_id,
                "new_state": session.state.value,
            }
        )

        return reply_text
