import re
from typing import Any, Optional
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import URLPattern, URLResolver, get_resolver
from django.views import View

# Graceful DRF support — DRF ships as part of the "django" extra (see
# pyproject.toml), so this should always be importable once DQS's Django
# adapter is installed. The try/except is defensive anyway, in case someone
# wires the adapter in unusually.
try:
    from rest_framework.views import APIView
    HAS_DRF = True
except ImportError:
    APIView = None
    HAS_DRF = False

# Graceful Django Channels (WebSocket) support. NOT executable in v1 — the
# Sandbox Runner has no WebSocket execution path (RequestFactory only builds
# plain HTTP requests). WebSocket routes are still discoverable here so the
# groundwork exists, but they're hidden from list_all_routes() output by
# default (see include_websockets below) so the Dashboard never shows a
# "Run" button for something that can't actually run yet.
try:
    from channels.routing import URLRouter
    HAS_CHANNELS = True
except ImportError:
    URLRouter = None
    HAS_CHANNELS = False


class DjangoIntrospector:
    """
    Finds every HTTP route registered in the host Django project, without the
    developer having to write any manual documentation or registration.

    Think of it like walking through a building floor by floor: Django's URL
    config is a tree of "hallways" (URLResolver — an include() pointing to
    more patterns) and "rooms" (URLPattern — an actual endpoint). This class
    walks that whole tree once and hands back a flat list of every room it
    found, labeled with what's inside (a DRF view? a plain Django view?
    which HTTP methods does it answer to?).
    """

    # DQS mounts its own dashboard under this prefix (see dqs/core/dashboard/urls.py).
    # Routes under this prefix are DQS's own UI, not the host project's
    # endpoints — excluded so the tool never lists (or lets someone "run")
    # itself.
    DQS_URL_PREFIX = "dqs/"

    def __init__(self, http_urlconf: Optional[Any] = None, ws_router: Optional[Any] = None) -> None:
        self.http_urlconf = http_urlconf
        self.ws_router = ws_router  # Expected to be a Channels URLRouter instance, if provided

    def list_all_routes(self, include_websockets: bool = False) -> dict[str, list[dict[str, Any]]]:
        """
        Returns discovered routes. `include_websockets` defaults to False —
        flip it on only once the Sandbox Runner actually supports executing
        WebSocket consumers (v2). Until then, showing them by default would
        let a user click "Run" on something guaranteed to fail confusingly.
        """
        # Same production guardrail the Sandbox Runner enforces — belt and
        # suspenders. Even if this class somehow gets imported/used outside
        # the DEBUG-only dashboard view, it refuses to enumerate routes.
        if not getattr(settings, "DEBUG", False):
            raise ImproperlyConfigured(
                "DjangoIntrospector may only run when settings.DEBUG=True."
            )

        result: dict[str, list[dict[str, Any]]] = {"http": self._get_http_routes()}
        if include_websockets:
            result["websocket"] = self._get_ws_routes()
        return result

    def _get_http_routes(self) -> list[dict[str, Any]]:
        resolver = get_resolver(self.http_urlconf)
        routes: list[dict[str, Any]] = []
        self._walk_patterns(resolver.url_patterns, prefix="", routes=routes, protocol="http")
        return routes

    def _get_ws_routes(self) -> list[dict[str, Any]]:
        routes: list[dict[str, Any]] = []
        if HAS_CHANNELS and isinstance(self.ws_router, URLRouter):
            self._walk_patterns(self.ws_router.routes, prefix="", routes=routes, protocol="ws")
        return routes

    def _walk_patterns(
        self,
        patterns: list[Any],
        prefix: str,
        routes: list[dict[str, Any]],
        protocol: str,
    ) -> None:
        for pattern in patterns:
            # CASE 1: this is a hallway with more doors inside (an include()).
            # Recurse into it, remembering the path prefix we walked through
            # to get here, so the final path is complete (e.g. "api/" + "books/").
            if isinstance(pattern, URLResolver) or (HAS_CHANNELS and hasattr(pattern, "routes")):
                nested_prefix = prefix + str(pattern.pattern)
                nested_patterns = getattr(pattern, "url_patterns", getattr(pattern, "routes", []))
                self._walk_patterns(nested_patterns, nested_prefix, routes, protocol)

            # CASE 2: this is an actual endpoint (a "room").
            elif isinstance(pattern, URLPattern) or hasattr(pattern, "callback"):
                raw_path = prefix + str(pattern.pattern)
                # Regex anchors (^ $) are parsing artifacts, not meaningful
                # to a human reading the endpoint list — strip them for display.
                # IMPORTANT: this cleaned path is for DISPLAY ONLY. If the
                # pattern contains a converter like <int:pk> or a regex
                # capture group, this string is NOT directly callable —
                # something upstream (Dashboard + Mock Data Generator) still
                # needs to substitute a real value before the Sandbox Runner
                # can hit it. See `has_path_params` below.
                clean_path = "/" + re.sub(r"[\^\$]", "", raw_path).lstrip("/")

                # Skip DQS's own dashboard routes so the tool never lists (or offers to "run") itself.
                if clean_path.lstrip("/").startswith(self.DQS_URL_PREFIX):
                    continue

                if protocol == "http":
                    route_info = self._inspect_http_pattern(pattern, clean_path)
                else:
                    route_info = self._inspect_ws_pattern(pattern, clean_path)

                if route_info:
                    routes.append(route_info)

    def _inspect_ws_pattern(self, pattern: Any, path: str) -> dict[str, Any]:
        """Inspects a Django Channels WebSocket consumer route."""
        callback = pattern.callback
        view_name = f"{callback.__module__}.{getattr(callback, '__name__', str(callback))}"
        return {
            "path": path,
            "protocol": "websocket",
            "view_name": view_name,
            "type": "Consumer",
            # Always False in v1, flagged explicitly so the Dashboard knows not to render a "Run" button for these yet.
            "executable": False,
        }

    def _inspect_http_pattern(self, pattern: URLPattern, path: str) -> Optional[dict[str, Any]]:
        callback = pattern.callback
        view_cls = getattr(callback, "view_class", None)
        view_name = f"{callback.__module__}.{getattr(callback, '__name__', str(callback))}"

        allowed_methods: list[str] = []
        view_type = "FBV"
        is_drf = False
        # True if we could confidently determine which HTTP methods this route answers to. If False, we skip the route entirely rather than guess — a wrong guess (e.g. "ALL") could make the Sandbox Runner try a method the view doesn't actually support.
        methods_known = False

        if view_cls:
            view_name = f"{view_cls.__module__}.{view_cls.__name__}"

            # WORKER TYPE 1: DRF class-based view (APIView / ViewSet).
            # NOTE: because Django's own View.as_view() already sets `view_class` before DRF adds `.cls` on top, an @api_view function-based view ALSO lands in this branch (it's built on a dynamically generated APIView subclass under the hood) — so in practice this branch covers both real DRF classes and @api_view functions. The "DRF_FBV" branch further down is kept for clarity/defensiveness but rarely fires because of this.
            if HAS_DRF and issubclass(view_cls, APIView):
                view_type = "DRF_CBV"
                is_drf = True
                methods_known = True

                if hasattr(callback, "actions"):
                    # ViewSet bound via a router — `actions` is the exact {http_method: action_name} mapping for THIS route (e.g. the list route might only bind get/post, while the detail route binds get/put/patch/delete). Using this instead of the class's full http_method_names avoids listing methods this specific route doesn't actually support.
                    allowed_methods = [m.upper() for m in callback.actions.keys()]
                else:
                    allowed_methods = [
                        m.upper() for m in view_cls.http_method_names
                        if m.lower() not in ("options", "trace") and hasattr(view_cls, m)
                    ]

            # WORKER TYPE 2: standard Django class-based view.
            elif issubclass(view_cls, View):
                view_type = "Django_CBV"
                methods_known = True
                allowed_methods = [
                    m.upper() for m in view_cls.http_method_names
                    if hasattr(view_cls, m.lower())
                ]

        else:
            # WORKER TYPE 3: DRF function-based view (@api_view) — kept for defensiveness; see note above on why this rarely triggers.
            if hasattr(callback, "cls") and HAS_DRF and issubclass(getattr(callback, "cls"), APIView):
                view_type = "DRF_FBV"
                is_drf = True
                methods_known = True
                allowed_methods = [m.upper() for m in getattr(callback.cls, "http_method_names", [])]

            # WORKER TYPE 4: plain Django function-based view with no way to confidently determine which methods it handles (e.g. no @require_http_methods decorator, dispatch logic buried in the function body). Per the roadmap, this case is explicitly punted — we skip it rather than guess, since a wrong guess could make the Sandbox Runner attempt an unsupported method.
            else:
                view_type = "Django_FBV"
                methods_known = False

        if not methods_known or not allowed_methods:
            return None

        return {
            "path": path,
            "protocol": "http",
            "methods": allowed_methods,
            "view_name": view_name,
            "view_type": view_type,
            "is_drf": is_drf,
            "executable": True,
            # True if the path contains a converter (<int:pk>) or a regex capture group — a signal to the Dashboard/Mock Data Generator that this route needs a real value substituted before the Sandbox Runner can actually call it. Substitution logic itself isn't solved here, this is just the flag that says "heads up."
            "has_path_params": bool(re.search(r"<[^>]+>|\(\?P<", path)),
        }