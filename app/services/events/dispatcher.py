"""Event dispatcher service for event-driven coordination."""

import logging
from typing import Any, Callable, Dict, List

from app.models.events import BaseEvent

logger = logging.getLogger("app.service.events.dispatcher")

# Typed signature for event handlers
EventHandlerCallable = Callable[[Any], Any]


class EventDispatcher:
    """Main event dispatcher managing subscribers and propagating events."""

    def __init__(self) -> None:
        """Initializes empty event registry mapping."""
        self._registry: Dict[str, List[EventHandlerCallable]] = {}

    def register(self, event_type: str, handler: EventHandlerCallable) -> None:
        """Registers a handler callable for a specific event type.

        Args:
            event_type: String identifier of the event type (e.g. 'whatsapp.message_received').
            handler: Callable function to execute when the event occurs.
        """
        if event_type not in self._registry:
            self._registry[event_type] = []
        self._registry[event_type].append(handler)
        
        handler_name = getattr(handler, "__name__", handler.__class__.__name__)
        logger.info(
            f"Registered event listener handler '{handler_name}' for type '{event_type}'",
            extra={
                "event": "handler_listener_registered",
                "event_type": event_type,
                "handler": handler_name
            }
        )

    async def dispatch(self, app_event: BaseEvent) -> None:
        """Asynchronously dispatches an event to all registered listeners.

        Args:
            app_event: Subclass instance of BaseEvent containing payload.
        """
        event_type = app_event.event_type
        handlers = self._registry.get(event_type, [])

        if not handlers:
            logger.debug(
                f"No handlers found listening for event type '{event_type}'",
                extra={"event": "event_no_listeners", "event_type": event_type}
            )
            return

        logger.info(
            f"Dispatching event '{event_type}' (id={app_event.event_id}) to {len(handlers)} listener(s)",
            extra={
                "event": "event_dispatch_started",
                "event_type": event_type,
                "event_id": app_event.event_id,
                "listeners": len(handlers)
            }
        )

        for handler in handlers:
            try:
                # Support both async and sync handler executions
                if hasattr(handler, "__call__"):
                    import inspect
                    is_async = inspect.iscoroutinefunction(handler) or inspect.iscoroutinefunction(handler.__call__)
                    if is_async:
                        await handler(app_event)
                    else:
                        handler(app_event)
            except Exception as exc:
                # Catch handler-specific issues to prevent stopping subsequent handlers
                handler_name = getattr(handler, "__name__", handler.__class__.__name__)
                logger.exception(
                    f"Failed executing handler '{handler_name}' on event '{event_type}': {exc}",
                    extra={
                        "event": "event_handler_failed",
                        "event_type": event_type,
                        "event_id": app_event.event_id,
                        "handler": handler_name,
                        "error": str(exc)
                    }
                )
