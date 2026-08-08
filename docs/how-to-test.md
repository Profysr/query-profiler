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

### Step 3: Configure Shadow Database (Recommended)

To isolate your default database from testing telemetry, configure a `'dqs_shadow'` entry in your `settings.DATABASES` matching your backend engine:

```python
# settings.py
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "my_db",
        "USER": "db_user",
        "PASSWORD": "db_password",
        "HOST": "localhost",
        "PORT": "5432",
    },
    "dqs_shadow": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "my_db_shadow",
        "USER": "db_user",
        "PASSWORD": "db_password",
        "HOST": "localhost",
        "PORT": "5432",
    },
}
```

To initialize or update your shadow database schema, execute migrations against the `dqs_shadow` database:

```bash
python manage.py migrate --database=dqs_shadow
```

### Step 4: Safe Execution Context (`profiling_session`)

Wrap any custom execution or seeding block in the `profiling_session()` context manager to route queries to `dqs_shadow`:

```python
from dqs.adapters.drf.router import profiling_session
from dqs.adapters.drf.mocking.generator import ModelBakeryGenerator

with profiling_session():
    # 1. Capped seeding (seeds up to 50 records if count < 1)
    ModelBakeryGenerator.ensure_capped_seeding("sample_app.Book", min_threshold=1, max_cap=50)
    
    # 2. View execution or ORM queries hit 'dqs_shadow'
```

---

## 2. Using Da Profiler to Optimize Your Django Code

### Approach A: Python Programmatic Profiling (CLI / Scripts / Management Commands)

You can discover targets and profile any endpoint or Python callable programmatically:

```python
from dqs.adapters.drf.execution.discovery import DjangoTargetDiscovery
from dqs.adapters.drf.execution.runner import DjangoSandboxRunner
from dqs.adapters.drf.routing.converters import PathConverterResolver
from dqs.adapters.drf.mocking.generator import infer_request_body

# 1. Discover all endpoints and signals in your Django project
targets = DjangoTargetDiscovery().discover_all()
for t in targets:
    print(f"Discovered Target: {t.id} (kind={t.kind}, triggerable={t.triggerable})")

# 2. Pick a target endpoint to profile (e.g. GET /api/v1/books/)
runner = DjangoSandboxRunner()
result = runner.execute_isolated(
    url_name_or_path="/api/v1/books/",
    method="GET",
)

# 3. Inspect captured SQL queries & N+1 findings
print(f"Status Code: {result.status_code}")
print(f"Total Queries Executed: {result.metrics['total_queries']}")

for n1 in result.analysis:
    print("--------------------------------------------------")
    print(f"🚨 Potential N+1 Bottleneck: {n1['fingerprint']}")
    print(f"📍 Location in Code: {n1['src_loc']}")
    print(f"🔁 Repeat Count: {n1['count']}")
    print(f"💡 Recommended Fix: {n1['suggestion']}")
```

---

### Approach B: Parameterized Endpoint Profiling (`/books/<int:pk>/`)

For dynamic URL routes requiring parameters:

```python
from dqs.adapters.drf.routing.converters import PathConverterResolver
from dqs.adapters.drf.routing.introspector import DjangoIntrospector

# 1. Discover routes to find the one you want
introspector = DjangoIntrospector()
routes = introspector.list_all_routes()

# 2. Find your route (e.g., book-detail)
target_route = next(r for r in routes if r.view_name == "book-detail")

# 3. Automatically resolve path converters using Model lookup or mock seeding
resolved_url, resolved_params, _ = PathConverterResolver.build_executable_url(
    route=target_route,
    explicit_params={},  # Leave empty to auto-generate
    auto_generate_if_missing=True,
)
# Produces valid concrete URL: "/api/v1/books/42/"

# 4. Run sandbox profiling with resolved parameters
runner = DjangoSandboxRunner()
result = runner.execute_isolated(
    url_name_or_path=resolved_url,
    method="GET",
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

#### Option 1: From Source Repository (Recommended)

```bash
# 1. Install package in editable mode with dev dependencies
pip install -e ".[dev]"

# 2. Go to demo project for Django tests
cd demos/drf

# 3. Run migrations on shadow database
python manage.py migrate --database=dqs_shadow

# 4. Run tests
pytest -m core        # Pure Python tests (fastest — no DB, no Django setup)
pytest -m django      # Django/DRF adapter tests
pytest -v             # All tests with verbose output
```

#### Option 2: Docker Compose (Full Stack)

```bash
# From repository root
docker compose build
docker compose up -d db
docker compose up -d

# Run tests inside container
docker compose exec web pytest -m core
docker compose exec web pytest -m django
```

#### Option 3: Install Built Package in Demo Project

```bash
# 1. Build the package
pip install build
python -m build

# 2. Install in demo project
cd demos/drf
pip install ../../dist/da_profiler-0.3.0-py3-none-any.whl[django]

# 3. Run migrations and tests
python manage.py migrate --database=dqs_shadow
pytest -m core
pytest -m django
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