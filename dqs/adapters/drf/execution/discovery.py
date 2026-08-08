import inspect
import logging
from typing import Any
import importlib
from django.conf import settings
from django.apps import apps

from dqs.adapters.drf.execution.schema_advisor import (
    check_missing_indexes,
    check_pk_strategy,
)
from dqs.core.static_advisor import StaticASTAdvisor
from dqs.core.targets import Target

logger = logging.getLogger("dqs")

"""
In a Django application, code is triggered in three main ways:

- Views: Triggered by HTTP requests sent to URL routes.
- Signals: Triggered automatically when database actions occur (e.g., post_save after a model is saved).
- Celery Tasks: Triggered asynchronously as background jobs.

DjangoTargetDiscovery scans the entire running Django project to collect all three of these entry points and wrap them into unified Target data objects so DQS can analyze and profile them equally.
"""

class DjangoTargetDiscovery:
    """
    Discovers all execution targets in a Django project (URL routes, signal receivers, 
    and Celery tasks), unifying them into standardized Target records.
    """
    def __init__(self, introspector_routes: list[Any] | None = None):
        self.introspector_routes = introspector_routes or []

    def discover_all(self) -> list[Target]:
        targets: list[Target] = []

        # 1. Map Introspected URL Routes into Targets
        # for route in self.introspector_routes:
        #     targets.append(Target(
        #         id=f"view:{route.path}",
        #         kind="view",
        #         triggerable=route.executable,
        #         trigger_spec={
        #             "path": route.path,
        #             "methods": route.methods,
        #             "path_params": [p.__dict__ for p in route.path_params],
        #             "target_model": route.target_model,
        #         },
        #         static_findings=[],
        #     ))

        for route in self.introspector_routes:
            static_findings = []
            static_findings.extend(check_pk_strategy(route.target_model))

            # Best-effort: try to statically analyze the view's own source for queried field names, to feed the missing-index check. Not always resolvable (e.g. ViewSets with dynamically dispatched methods), so failures here are silently skipped rather than raised.
            queried_fields = []
            view_callable = getattr(route, "view_callable", None)  # only if introspector exposes it
            if view_callable is not None:
                try:
                    import inspect
                    source = inspect.getsource(view_callable)
                    advisor = StaticASTAdvisor(source)
                    advisor.run()
                    queried_fields = advisor.queried_fields
                except (TypeError, OSError, Exception):
                    pass
            static_findings.extend(check_missing_indexes(route.target_model, queried_fields))

            targets.append(Target(
                id=f"view:{route.path}",
                kind="view",
                triggerable=route.executable,
                trigger_spec={
                    "path": route.path,
                    "methods": route.methods,
                    "path_params": [p.__dict__ for p in route.path_params],
                    "target_model": route.target_model,
                },
                static_findings=static_findings,
            ))

        # 2. Discover Django Model Signals (NOTE: Not implemented yet. Will add signal handling in the future.)
        # signal_mappings = [
        #     ("post_save", post_save),
        #     ("pre_save", pre_save),
        #     ("post_delete", post_delete),
        #     ("pre_delete", pre_delete),
        # ]

        # for sig_name, signal_obj in signal_mappings:
        #     try:
        #         # _live_receivers(sender) yields active (receiver_key, receiver_func) pairs
        #         for receiver_key, func_obj in signal_obj._live_receivers(None):
        #             if not callable(func_obj):
        #                 continue

        #             func_name = getattr(func_obj, "__name__", "anonymous_receiver")
                    
        #             # receiver_key is typically a tuple like (sender_class_or_none, dispatch_uid)
        #             sender_id = receiver_key[0] if isinstance(receiver_key, tuple) and len(receiver_key) > 0 else None
        #             sender_model = self._resolve_sender_model(sender_id)

        #             is_triggerable = sender_model is not None
        #             target_id = f"signal:{sig_name}:{func_name}"

        #             if any(t.id == target_id for t in targets):
        #                 continue

        #             targets.append(Target(
        #                 id=target_id,
        #                 kind="signal",
        #                 triggerable=is_triggerable,
        #                 trigger_spec={
        #                     "signal": sig_name,
        #                     "receiver": func_name,
        #                     "sender_model": sender_model,
        #                 },
        #                 static_findings=self._analyze_callable_statically(func_obj),
        #             ))
        #     except Exception as e:
        #         logger.debug(f"Could not inspect signal {sig_name}: {e}")

        # 3. Discover Celery Background Tasks
        try:
            from celery import current_app
            for task_name, task_func in current_app.tasks.items():
                if task_name.startswith("celery."):
                    continue
                targets.append(Target(
                    id=f"task:{task_name}",
                    kind="task",
                    triggerable=True,
                    trigger_spec={
                        "task_name": task_name,
                    },
                    static_findings=self._analyze_callable_statically(task_func),
                ))
        except (ImportError, Exception):
            pass
        # 4. Discover Channels WebSocket consumers (discovery only, not executable yet)
        targets.extend(self._discover_consumers())
        
        return targets

    def _discover_consumers(self) -> list[Target]:
        """
        Discovers Channels WebSocket consumers via the project's ASGI routing
        (settings.ASGI_APPLICATION -> ProtocolTypeRouter -> websocket URLRouter).
        Per roadmap: discovery only for now — triggerable=False. A fundamentally
        different trigger mechanism than RequestFactory/direct-call is needed for
        actual execution, which is explicitly v2.0+ scope.
        """
        targets: list[Target] = []
        try:

            asgi_path = getattr(settings, "ASGI_APPLICATION", None)
            if not asgi_path:
                return targets

            module_path, app_attr = asgi_path.rsplit(".", 1)
            asgi_module = importlib.import_module(module_path)
            asgi_app = getattr(asgi_module, app_attr, None)

            websocket_router = getattr(asgi_app, "application_mapping", {}).get("websocket")
            routes = getattr(websocket_router, "routes", [])

            for route in routes:
                callback = getattr(route, "callback", None)
                consumer_class = getattr(callback, "consumer_class", None) or callback
                if consumer_class is None:
                    continue

                name = getattr(consumer_class, "__name__", "UnknownConsumer")
                targets.append(Target(
                    id=f"consumer:{name}",
                    kind="consumer",
                    triggerable=False,
                    trigger_spec={
                        "consumer": name,
                        "path": str(getattr(route, "pattern", "")),
                    },
                    static_findings=self._analyze_callable_statically(consumer_class),
                ))
        except Exception as e:
            logger.debug(f"Could not discover Channels consumers: {e}")

        return targets

    def _analyze_callable_statically(self, func: Any) -> list[dict[str, Any]]:
        if not callable(func):
            return []
        try:
            source = inspect.getsource(func)
            filename = inspect.getfile(func)
            advisor = StaticASTAdvisor(source, filename=filename)
            return advisor.run()
        except (TypeError, OSError, Exception):
            return []

    def _resolve_sender_model(self, sender_id: int | None) -> str | None:
        """
        Django stores signal sender association as id(sender_class), not the class itself. Reverse-resolve it back to 'app_label.ModelName' by scanning installed models, this is what makes a signal actually
        triggerable later (we need to know which model to save/delete).
        Returns None for wildcard receivers (sender=None, applies to all senders).
        """
        if sender_id is None:
            return None
        for model in apps.get_models():
            if id(model) == sender_id:
                return f"{model._meta.app_label}.{model._meta.object_name}"
        return None