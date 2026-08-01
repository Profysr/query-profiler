from dataclasses import dataclass, field
from typing import Literal, Dict, Any, List, Optional

TargetKind = Literal["view", "signal", "task", "consumer", "static_only"]

@dataclass
class Target:
    id: str
    kind: TargetKind
    triggerable: bool
    trigger_spec: Optional[Dict[str, Any]] = None
    static_findings: List[Dict[str, Any]] = field(default_factory=list)