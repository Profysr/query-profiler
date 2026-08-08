"""
Backward-compatibility adapter module for dqs.adapters.drf.
Re-exports components from subdirectories (mocking, routing, execution)
to preserve existing import paths across the codebase.
"""

from dqs.adapters.drf.execution.runner import DjangoSandboxRunner
from dqs.adapters.drf.types import ExecutionResult

from dqs.adapters.drf.mocking.generator import (
    MockValueGenerator,
    ModelBakeryGenerator,
    infer_body_from_fields,
    infer_request_body,
)
from dqs.adapters.drf.routing.converters import PathConverterResolver
from dqs.adapters.drf.routing.introspector import DjangoIntrospector
from dqs.adapters.drf.types import PathParam, RouteMetadata, SeedDataRequiredError

__all__ = [
    "DjangoIntrospector",
    "DjangoSandboxRunner",
    "ExecutionResult",
    "ModelBakeryGenerator",
    "PathConverterResolver",
    "PathParam",
    "RouteMetadata",
    "SeedDataRequiredError",
    "MockValueGenerator",
    "ModelBakeryGenerator",
    "infer_body_from_fields",
    "infer_request_body",
]
