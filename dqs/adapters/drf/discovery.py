import inspect
import logging
from typing import Any, Dict, List, Optional
from django.db.models.signals import post_save, pre_save, post_delete, pre_delete
from dqs.core.targets import Target
from dqs.core.static_advisor import StaticASTAdvisor
from django.apps import apps
import weakref

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
    def __init__(self, introspector_routes: Optional[List[Any]] = None):
        self.introspector_routes = introspector_routes or []

    def discover_all(self) -> List[Target]:
        targets: List[Target] = []

        # 1. Map Introspected URL Routes into Targets
        for route in self.introspector_routes:
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
                static_findings=[],
            ))

        # 2. Discover Django Model Signals
        signal_mappings = [
            ("post_save", post_save),
            ("pre_save", pre_save),
            ("post_delete", post_delete),
            ("pre_delete", pre_delete),
        ]

        for sig_name, signal_obj in signal_mappings:
            try:
                for lookup_key, receiver_ref in signal_obj.receivers:
                    
                    # 1. Unwrap the actual function from memory
                    if isinstance(receiver_ref, weakref.ReferenceType):
                        func_obj = receiver_ref()  
                    else:
                        func_obj = receiver_ref    
                        
                    # 2. Skip if the function was deleted from memory or is invalid
                    if not callable(func_obj):
                        continue

                    # 3. Safely get the name of the function
                    func_name = getattr(func_obj, "__name__", "anonymous_receiver")

                    # 4. Resolve which model actually triggers this signal —
                    #    without this, there's no way to synthesize a trigger event.
                    sender_id = lookup_key[1] if isinstance(lookup_key, tuple) and len(lookup_key) > 1 else None
                    sender_model = self._resolve_sender_model(sender_id)

                    # Wildcard receivers (sender=None, fire on ANY model) can't be
                    # safely auto-triggered — we'd have to guess which model to
                    # save/delete. Mark them discovered but not triggerable.
                    is_triggerable = sender_model is not None

                    targets.append(Target(
                        id=f"signal:{sig_name}:{func_name}",
                        kind="signal",
                        triggerable=is_triggerable,
                        trigger_spec={
                            "signal": sig_name,
                            "receiver": func_name,
                            "sender_model": sender_model,
                        },
                        static_findings=self._analyze_callable_statically(func_obj),
                    ))
            except Exception as e:
                logger.debug(f"Could not inspect signal {sig_name}: {e}")

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

        return targets

    def _analyze_callable_statically(self, func: Any) -> List[Dict[str, Any]]:
        if not callable(func):
            return []
        try:
            source = inspect.getsource(func)
            filename = inspect.getfile(func)
            advisor = StaticASTAdvisor(source, filename=filename)
            return advisor.run()
        except (TypeError, OSError, Exception):
            return []

    def _resolve_sender_model(self, sender_id: Optional[int]) -> Optional[str]:
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