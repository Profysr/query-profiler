# Integration, Profiling & Testing Guide 🧪

This guide walks you through integrating **Da Profiler** (`dqs`) into your Django / Django REST Framework application, running isolated query profiling sessions to detect N+1 bottlenecks, and running the package's test suite.

---

## 1. Package Integration Guide

### Step 1: Install Package

Install `da-profiler` from PyPI with Django support:

```bash
pip install da-profiler[django]
```

Or add it to your project dependencies (`pyproject.toml` or `requirements.txt`):

```toml
# pyproject.toml
[project]
dependencies = [
    "da-profiler[django]>=0.3.0",
]
```

### Step 2: Register in `INSTALLED_APPS`

Enable `dqs.adapters.drf` conditionally in your development environment (`settings.py`):

```python
# settings.py
INSTALLED_APPS = [
    ...
    # Existing Django / DRF apps
]

# Enable Da Profiler in development mode only
if DEBUG:
    INSTALLED_APPS += [
        "dqs.adapters.drf",
    ]
```

> ⚠️ **Guardrail Notice:** `Da Profiler` requires `DEBUG=True` to execute sandbox profiling and stack inspection safely. It will raise `ImproperlyConfigured` if invoked when `DEBUG=False`.

---

## 2. Using Da Profiler to Optimize Your Django Code

### Approach A: Python Programmatic Profiling (CLI / Scripts / Management Commands)

You can discover targets and profile any endpoint or Python callable programmatically:

```python
from dqs.adapters.drf.discovery import DjangoTargetDiscovery
from dqs.adapters.drf.runner import DjangoSandboxRunner
from dqs.adapters.drf.converters import PathConverterResolver
from dqs.adapters.drf.body_inferrer import infer_request_body

# 1. Discover all endpoints and signals in your Django project
targets = DjangoTargetDiscovery.discover_all()
for t in targets:
    print(f"Discovered Target: {t.id} (kind={t.kind}, triggerable={t.triggerable})")

# 2. Pick a target endpoint to profile (e.g. GET /api/v1/books/)
runner = DjangoSandboxRunner()
result = runner.execute_isolated(
    target_id="demo_project.views.BookListView",
    method="GET",
    path="/api/v1/books/",
)

# 3. Inspect captured SQL queries & N+1 findings
print(f"Status Code: {result['status_code']}")
print(f"Total Queries Executed: {result['query_count']}")

for n1 in result["n_plus_one_findings"]:
    print("--------------------------------------------------")
    print(f"🚨 Potential N+1 Bottleneck on Table: {n1['table']}")
    print(f"📍 Location in Code: {n1['source_location']}")
    print(f"🔁 Repeat Count: {n1['count']}")
    print(f"💡 Recommended Fix: {n1['suggestion']}")
```

---

### Approach B: Parameterized Endpoint Profiling (`/books/<int:pk>/`)

For dynamic URL routes requiring parameters:

```python
from dqs.adapters.drf.converters import PathConverterResolver

# Automatically resolve path converters using Model lookup or mock seeding
resolver = PathConverterResolver()
resolved_path = resolver.resolve_and_reverse("book-detail", {"pk": None})
# Produces valid concrete URL: "/api/v1/books/42/"

# Run sandbox profiling with resolved parameters
result = runner.execute_isolated(
    target_id="demo_project.views.BookDetailView",
    method="GET",
    path=resolved_path,
)
```

---

### Approach C: Autonomous AI Agent Optimization (MCP Server)

If you use Cursor, Windsurf, or Claude Code:

1. **Start the MCP Server**:
   ```bash
   python -m dqs.mcp.server
   ```
2. **Connect your AI IDE**: Configure your MCP client settings (`stdio` mode).
3. **Agent Loop**:
   - Agent calls `list_django_routes()` to inventory endpoints.
   - Agent calls `profile_endpoint(target="api-v1-books", method="GET")`.
   - Agent reads the exact AST finding (e.g. `sample_app/views.py:14` - `Add .select_related('author')`).
   - Agent rewrites `views.py` to add `.select_related('author')`.
   - Agent re-runs `profile_endpoint` to verify query count dropped (e.g. from `25` queries down to `2`).

---

## 3. Running Package Tests

Da Profiler uses **pytest** with a marker-based test architecture.

### Test Architecture

```
tests/
├── conftest.py                      # Root: marker registration
├── core/                            # Marker: `core` — pure Python, no DB
│   ├── conftest.py                  # Auto-marks all tests as `core`
│   ├── test_analyzer.py             # SQL AST fingerprinting & N+1 detection
│   └── test_static_advisor.py       # Python AST static code scanning
└── adapters/
    └── drf/                         # Marker: `django` + `drf` — requires DB
        ├── conftest.py              # Shared fixtures: runner, introspector, seeded_book
        ├── test_body_inferrer.py    # Request body inference tests
        ├── test_converters.py       # PathConverterResolver unit tests
        ├── test_discovery.py        # Signal & task discovery tests
        ├── test_introspector.py     # URL route scanning and lookup map tests
        ├── test_query_interceptor.py# DB execute_wrapper SQL capture tests
        ├── test_runner.py           # SandboxRunner & step-driven pipeline tests
        └── test_runner_integration.py # Setup isolation & savepoint rollback test
```

---

### Marker Taxonomy

| Marker | Meaning | Requires DB? | Speed |
|---|---|---|---|
| `core` | Pure Python (`dqs/core/`) — no Django, no ORM | No | ⚡ Fastest |
| `django` | Django ORM + DB access (`dqs/adapters/drf/`) | Yes | 🐢 Slower |
| `drf` | DRF adapter subset of django tests | Yes | 🐢 Slower |

---

### Running the Test Commands

```bash
# Run entire test suite inside Docker
docker compose run --rm <container_name> pytest

# Run only pure Python core tests (fastest — no DB, no Django setup)
docker compose run --rm <container_name> pytest -m core

# Run only Django/DRF adapter tests
docker compose run --rm <container_name> pytest -m django

# Run specific test file with verbose output
docker compose run --rm <container_name> pytest -v tests/adapters/drf/test_runner.py
```

---

## 4. Shared Test Fixtures (DRF adapter)

Available to tests in `tests/adapters/drf/`:

| Fixture | Type | Description |
|---|---|---|
| `runner` | `DjangoSandboxRunner` | Pre-initialized sandbox runner |
| `introspector` | `DjangoIntrospector` | Pre-initialized URL introspector |
| `seeded_book` | `Book` | Seeded `Publisher → Author → Book` relational record |
| `enforce_debug_mode` | `autouse` | Forces `DEBUG=True` for all DRF adapter tests |

