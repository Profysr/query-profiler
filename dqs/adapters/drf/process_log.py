"""
Process Logger — Simple step-by-step execution tracking for Da Profiler.
Unlike regular logs, process logs tell WHAT happened in plain language.
"""
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProcessStep:
    step: str
    message: str
    timestamp: float = field(default_factory=time.time)
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str | None = None


class ProcessLogger:
    """
    Thread-local process logger that captures execution flow in simple terms.
    Each profiling session gets its own log trace.
    """
    _local = threading.local()

    @classmethod
    def _get_log(cls) -> list[ProcessStep]:
        if not hasattr(cls._local, "steps"):
            cls._local.steps = []
        return cls._local.steps

    @classmethod
    def clear(cls) -> None:
        """Clear the process log for a new session."""
        cls._local.steps = []

    @classmethod
    def log(cls, step: str, message: str, **metadata) -> ProcessStep:
        """Add a process step."""
        entry = ProcessStep(step=step, message=message, metadata=metadata)
        cls._get_log().append(entry)
        return entry

    @classmethod
    def log_start(cls, step: str, message: str, **metadata) -> ProcessStep:
        """Log the start of an operation."""
        return cls.log(step, f"START: {message}", **metadata)

    @classmethod
    def log_success(cls, step: str, message: str, duration_ms: float | None = None, **metadata) -> ProcessStep:
        """Log successful completion."""
        entry = cls.log(step, f"OK: {message}", duration_ms=duration_ms, success=True, **metadata)
        return entry

    @classmethod
    def log_error(cls, step: str, message: str, error: str, duration_ms: float | None = None, **metadata) -> ProcessStep:
        """Log a failure."""
        entry = cls.log(step, f"FAILED: {message}", duration_ms=duration_ms, success=False, error=error, **metadata)
        return entry

    @classmethod
    def get_log(cls) -> list[dict[str, Any]]:
        """Get the process log as a list of dictionaries."""
        return [
            {
                "step": s.step,
                "message": s.message,
                "timestamp": s.timestamp,
                "duration_ms": s.duration_ms,
                "metadata": s.metadata,
                "success": s.success,
                "error": s.error,
            }
            for s in cls._get_log()
        ]

    @classmethod
    def get_summary(cls) -> str:
        """Get a human-readable summary of the process log."""
        lines = []
        for s in cls._get_log():
            status = "✓" if s.success else "✗"
            duration = f" ({s.duration_ms:.1f}ms)" if s.duration_ms else ""
            lines.append(f"  {status} {s.step}: {s.message}{duration}")
            if s.error:
                lines.append(f"      Error: {s.error}")
        return "\n".join(lines)


@contextmanager
def timed_step(step: str, message: str, **metadata):
    """Context manager to time and log a step."""
    start = time.perf_counter()
    ProcessLogger.log_start(step, message, **metadata)
    try:
        yield
        duration = (time.perf_counter() - start) * 1000
        ProcessLogger.log_success(step, message, duration_ms=duration, **metadata)
    except Exception as e:
        duration = (time.perf_counter() - start) * 1000
        ProcessLogger.log_error(step, message, error=str(e), duration_ms=duration, **metadata)
        raise