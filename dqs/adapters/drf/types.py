from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

@dataclass
class PathParam:
    name: str
    converter: str


@dataclass
class RouteMetadata:
    path: str
    methods: List[str]
    view_name: str
    view_type: str
    is_drf: bool = True
    executable: bool = True
    path_params: List[PathParam] = field(default_factory=list)
    target_model: Optional[str] = None
    reason_unexecutable: Optional[str] = None
    view_callable: Optional[Callable] = None

    @property
    def has_path_params(self) -> bool:
        return len(self.path_params) > 0