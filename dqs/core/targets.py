from dataclasses import dataclass, field
from typing import Any, Literal

TargetKind = Literal["view", "signal", "task", "consumer", "static_only"]

@dataclass
class Target:
    id: str
    kind: TargetKind
    triggerable: bool
    trigger_spec: dict[str, Any] | None = None
    static_findings: list[dict[str, Any]] = field(default_factory=list)