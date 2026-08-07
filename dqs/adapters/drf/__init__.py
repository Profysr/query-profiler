"""
Backward-compatibility adapter module for dqs.adapters.drf.
Re-exports components from subdirectories (mocking, routing, execution)
to preserve existing import paths across the codebase.
"""

from dqs.adapters.drf.types import PathParam, RouteMetadata, SeedDataRequiredError
from dqs.adapters.drf.mocking.generator import ValueInferenceEngine, ModelBakeryGenerator, infer_request_body, infer_body_from_serializer, infer_body_from_form
from dqs.adapters.drf.routing.converters import PathConverterResolver
from dqs.adapters.drf.routing.introspector import DjangoIntrospector
from dqs.adapters.drf.execution.runner import DjangoSandboxRunner, ExecutionResult

__all__ = [
    "PathParam",
    "RouteMetadata",
    "SeedDataRequiredError",
    "ValueInferenceEngine",
    "ModelBakeryGenerator",
    "infer_request_body",
    "infer_body_from_serializer",
    "infer_body_from_form",
    "PathConverterResolver",
    "DjangoIntrospector",
    "DjangoSandboxRunner",
    "ExecutionResult",
]
