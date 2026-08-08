from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PathParam:
    name: str
    converter: str


@dataclass
class RouteMetadata:
    path: str
    methods: list[str]
    view_name: str
    view_type: str
    is_drf: bool = True
    executable: bool = True
    path_params: list[PathParam] = field(default_factory=list)
    target_model: str | None = None
    reason_unexecutable: str | None = None
    view_callable: Callable | None = None
    lookup_map: dict[str, str] = field(default_factory=dict)

    @property
    def has_path_params(self) -> bool:
        return len(self.path_params) > 0


@dataclass
class ExecutionResult:
    """Encapsulates the execution metrics, query logs, and analysis payload for a profiled target."""

    route: str
    status_code: int
    metrics: dict[str, Any] = field(default_factory=dict)
    queries: list[dict[str, Any]] = field(default_factory=list)
    analysis: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    side_effect_warnings: list[str] = field(default_factory=list)
    response_body: Any | None = None
    seeded_records: list[dict[str, Any]] = field(default_factory=list)
    request_spec: dict[str, Any] | None = None


class SeedDataRequiredError(Exception):
    """Raised when automated mock generation fails, requiring user-provided JSON records."""
