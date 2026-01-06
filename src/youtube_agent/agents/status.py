"""Status monitoring for human-friendly progress updates."""

import logging
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import TextIO


@dataclass
class StatusEvent:
    """A status event for display."""

    timestamp: datetime
    message: str
    level: str = "info"


class StatusMonitor:
    """Monitors agent activity and provides human-friendly status updates.

    This class captures log messages and transforms them into readable
    status updates that are printed to the terminal.

    :param output: Output stream (defaults to stderr to not mix with results)
    :param max_events: Maximum events to keep in history
    """

    def __init__(
        self,
        output: TextIO = sys.stderr,
        max_events: int = 100,
    ) -> None:
        self._output = output
        self._events: deque[StatusEvent] = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._enabled = False

    def enable(self) -> None:
        """Enable status output."""
        self._enabled = True

    def disable(self) -> None:
        """Disable status output."""
        self._enabled = False

    def status(self, message: str, level: str = "info") -> None:
        """Record and display a status message.

        :param message: The status message
        :param level: Message level (info, success, warning, error)
        """
        event = StatusEvent(
            timestamp=datetime.now(),
            message=message,
            level=level,
        )

        with self._lock:
            self._events.append(event)

        if self._enabled:
            self._print_status(event)

    def _print_status(self, event: StatusEvent) -> None:
        """Print a status event to output."""
        # Use symbols for different levels
        symbols = {
            "info": "->",
            "success": "OK",
            "warning": "!!",
            "error": "XX",
            "working": "..",
        }
        symbol = symbols.get(event.level, "->")
        timestamp = event.timestamp.strftime("%H:%M:%S")
        print(f"[{timestamp}] {symbol} {event.message}", file=self._output)

    def get_recent_events(self, count: int = 10) -> list[StatusEvent]:
        """Get recent status events.

        :param count: Number of events to return
        :return: List of recent events
        """
        with self._lock:
            return list(self._events)[-count:]


class StatusLogHandler(logging.Handler):
    """Logging handler that converts log messages to status updates.

    Interprets log messages from the agent system and converts them
    to human-friendly status messages.
    """

    # Patterns to convert log messages to friendly status
    PATTERNS = {
        "Orchestrator received request": ("Received your request", "info"),
        "Calling Azure OpenAI": ("Thinking...", "working"),
        "Orchestrator completed": ("Done thinking", "success"),
        "SearchAgent called": ("Searching YouTube", "working"),
        "SearchAgent response": ("Found videos", "success"),
        "TranscriptAgent called": ("Fetching transcript", "working"),
        "TranscriptAgent response": ("Got transcript", "success"),
        "SummarizeAgent called": ("Generating summary", "working"),
        "SummarizeAgent response": ("Summary ready", "success"),
        "Cache hit for video": ("Using cached transcript", "success"),
        "Cache miss for video": ("Fetching from YouTube", "working"),
    }

    def __init__(self, monitor: StatusMonitor) -> None:
        super().__init__()
        self._monitor = monitor

    def emit(self, record: logging.LogRecord) -> None:
        """Process a log record and emit status if relevant."""
        message = record.getMessage()

        # Check for known patterns
        for pattern, (friendly_msg, level) in self.PATTERNS.items():
            if pattern in message:
                self._monitor.status(friendly_msg, level)
                return

        # For HTTP requests, show simplified status
        if "httpx" in record.name:
            if "HTTP Request: POST" in message:
                self._monitor.status("Calling AI service...", "working")
            elif "HTTP Response" in message and "200" in message:
                self._monitor.status("AI response received", "success")


# Global status monitor instance
_status_monitor: StatusMonitor | None = None


def get_status_monitor() -> StatusMonitor:
    """Get the global status monitor instance."""
    global _status_monitor
    if _status_monitor is None:
        _status_monitor = StatusMonitor()
    return _status_monitor


def setup_status_monitoring() -> StatusMonitor:
    """Set up status monitoring with log integration.

    :return: The configured StatusMonitor
    """
    monitor = get_status_monitor()
    monitor.enable()

    # Add handler to capture agent logs
    handler = StatusLogHandler(monitor)
    handler.setLevel(logging.DEBUG)

    # Attach to relevant loggers and ensure they emit DEBUG messages
    # (even if root logger is at WARNING level)
    for logger_name in ["youtube_agent", "httpx"]:
        log = logging.getLogger(logger_name)
        log.addHandler(handler)
        # Ensure logger level allows DEBUG messages to flow to our handler
        if log.level == logging.NOTSET or log.level > logging.DEBUG:
            log.setLevel(logging.DEBUG)

    return monitor
