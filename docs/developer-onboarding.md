# 🛠️ Open Source Developer Onboarding & File Reference Guide

Welcome to the **Da Profiler** contributor guide! This document provides a complete file-by-file walkthrough of the codebase, explaining what every single module does and how they connect together.

---

## 🗺️ Architectural Core: The 1-Way Dependency Rule

Da Profiler strictly enforces a **one-way architectural boundary**:
- **Core (`dqs/core/`)**: Framework-agnostic engine. **Zero Django or framework imports.**
- **Adapters (`dqs/adapters/`)**: Framework-specific integration layer (e.g. Django/DRF).

```
dqs/core/ (Zero framework imports)  <───  dqs/adapters/drf/ (Django specific)
```

---

## 📁 File-by-File Codebase Reference

Below is the complete reference map for every file in the repository:

### 1. Core Engine (`dqs/core/`) — Framework-Agnostic

| File | Primary Purpose & Key Functions |
| :--- | :--- |
| [`dqs/core/analyzer.py`](../dqs/core/analyzer.py) | **SQL AST Fingerprinting & N+1 Detection**: Uses `sqlglot` to parse raw SQL into Abstract Syntax Trees, strip dynamic numeric/string literals, collapse `IN (...)` clauses, and canonicalize table aliases. Functions: `fingerprint()`, `detect_n_plus_one()`, `suggest_fix()`. |
| [`dqs/core/static_advisor.py`](../dqs/core/static_advisor.py) | **Static AST Analyzer**: Pure AST scanner that inspects user Python source code without execution. Detects ORM queries inside `for`/`async for` loops and flags blocking synchronous I/O (`requests`, `smtplib`, `time.sleep`) resolving import aliases (`import X as Y`, `from X import Y`). |
| [`dqs/core/targets.py`](../dqs/core/targets.py) | **Target Data Model**: Defines the unified `Target` dataclass (`id`, `kind`, `triggerable`, `trigger_spec`, `static_findings`) unifying views, signals, Celery tasks, and consumers under a single schema. |

---

### 2. Django & DRF Adapter (`dqs/adapters/drf/`)

| File | Primary Purpose & Key Functions |
| :--- | :--- |
| [`dqs/adapters/drf/__init__.py`](../dqs/adapters/drf/__init__.py) | Package init, exports public API. |
| [`dqs/adapters/drf/apps.py`](../dqs/adapters/drf/apps.py) | **Django AppConfig**: Registers Da Profiler as a Django app (`dqs.adapters.drf`). Enforces safety check on startup ensuring `settings.DEBUG == True`. |
| [`dqs/adapters/drf/router.py`](../dqs/adapters/drf/router.py) | **Shadow DB Router & Session Manager**: `DQSRouter` routes DB operations to `dqs_shadow` when `profiling_session()` is active. Thread-local storage for safety. |
| [`dqs/adapters/drf/types.py`](../dqs/adapters/drf/types.py) | **Shared Dataclasses**: `PathParam`, `RouteMetadata`, `ExecutionResult`, `SeedDataRequiredError`. |
| [`dqs/adapters/drf/views.py`](../dqs/adapters/drf/views.py) | **Web Dashboard & AJAX Endpoints**: `DQSDashboardView` (GET `/dqs/`), `DQSProfileView` (POST `/dqs/profile/`). |
| [`dqs/adapters/drf/urls.py`](../dqs/adapters/drf/urls.py) | **URL Configuration**: Mounts dashboard at `/dqs/`. |
| [`dqs/adapters/drf/database/db_manager.py`](../dqs/adapters/drf/database/db_manager.py) | **Shadow DB Validation**: Validates `dqs_shadow` in `DATABASES` and `DQSRouter` in `DATABASE_ROUTERS`. Runs migrations programmatically. |
| [`dqs/adapters/drf/routing/introspector.py`](../dqs/adapters/drf/routing/introspector.py) | **URL Pattern Introspector**: `DjangoIntrospector.list_all_routes()` recursively walks Django's `urlpatterns` tree, classifying endpoints as DRF `ViewSet`, `APIView`, FBV, or CBV. Safely reports `executable=False` when routes cannot be statically resolved. |
| [`dqs/adapters/drf/routing/converters.py`](../dqs/adapters/drf/routing/converters.py) | **Path Converter Engine**: `PathConverterResolver` resolves parameterized routes using DB lookup, DRF `lookup_field`/`lookup_url_kwarg` mapping, and `model_bakery` mock seeding fallback. |
| [`dqs/adapters/drf/mocking/generator.py`](../dqs/adapters/drf/mocking/generator.py) | **Mock Data & Body Generator**: `ModelBakeryGenerator` wraps `model_bakery` with constraint safety, uniqueness guards, validation recovery, and user record cloning. `infer_request_body()` generates mock payloads from DRF serializers or Django forms. |
| [`dqs/adapters/drf/execution/discovery.py`](../dqs/adapters/drf/execution/discovery.py) | **Target Discovery Engine**: `DjangoTargetDiscovery.discover_all()` finds Django URL endpoints, signal receivers (`post_save`, `pre_save`, `post_delete`), Celery tasks, and Channels ASGI consumers. Integrates `schema_advisor.py` checks and feeds callables through `StaticASTAdvisor`. |
| [`dqs/adapters/drf/execution/query_interceptor.py`](../dqs/adapters/drf/execution/query_interceptor.py) | **DB Driver Boundary Interceptor**: `QueryInterceptor` context manager hooks into Django's `connection.execute_wrapper()`. Captures SQL, duration, and walks `inspect.stack()` to attribute queries to user code line numbers. `QueryAnalysisEngine` formats results and runs N+1 detection via `dqs.core.analyzer`. |
| [`dqs/adapters/drf/execution/runner.py`](../dqs/adapters/drf/execution/runner.py) | **Sandbox Execution Engine**: `DjangoSandboxRunner` orchestrates isolated execution via `profile_callable()` (savepoint + interceptor) and `execute_isolated()` (full HTTP request pipeline with mock seeding, side-effect detection, and result formatting). Contains helper classes: `StaticAnalysisService`, `RequestSpecBuilder`, `TargetExecutor`. |
| [`dqs/adapters/drf/execution/schema_advisor.py`](../dqs/adapters/drf/execution/schema_advisor.py) | **Schema & Index Advisor**: `check_pk_strategy()` flags auto-increment PKs (recommends UUIDv7). `check_missing_indexes()` cross-references queried fields against model indexes (`db_index`, `unique`, `Meta.indexes`). |

---

### 3. Demo Application (`demos/drf/`)

| File | Primary Purpose |
| :--- | :--- |
| [`demos/drf/sample_app/models.py`](../demos/drf/sample_app/models.py) | Sample relational models (`Author`, `Book`, `Publisher`) used for integration testing. |
| [`demos/drf/sample_app/views.py`](../demos/drf/sample_app/views.py) | Intentionally flawed endpoints (e.g. `NPlusOneBookListView`) used to test and validate Da Profiler's N+1 detection. |
| [`demos/drf/config/urls.py`](../demos/drf/config/urls.py) | Root URL resolver mapping sample app routes. |

---

### 4. System & Project Configuration Files

| File | Primary Purpose |
| :--- | :--- |
| [`pyproject.toml`](../pyproject.toml) | Packaging configuration, dependencies (`sqlglot>=26.0.0`), optional extras (`[django]`, `[dev]`), and pytest configuration. |
| [`architecture.md`](../architecture.md) | Technical architecture document, component sequence diagrams, and design principles. |
| [`README.md`](../README.md) | Primary project homepage, feature highlights, and dev quickstart. |
| [`ROADMAP.md`](../ROADMAP.md) | Version roadmap tracking completed phases (v0.1, v0.2, v0.25) and planned phases (v0.3, v0.4 MCP, v1.0). |
| [`CHANGELOG.md`](../CHANGELOG.md) | Historical record of changes, additions, fixes, and architectural revisions. |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Guidelines for opening issues, writing PRs, coding standards, and running tests. |

---

## 🛠️ Setting Up Your Local Environment

```bash
# 1. Clone repository
git clone https://github.com/your-org/da-profiler.git
cd da-profiler

# 2. Install in editable mode with dev dependencies
pip install -e ".[dev]"

# 3. Go to demo project and run migrations
cd demos/drf
python manage.py migrate --database=dqs_shadow

# 4. Run Pytest Suite
pytest -m core        # Pure Python tests (fastest)
pytest -m django      # Django/DRF adapter tests
pytest                # All tests
```

---

## 🎯 How to Add New Features

1. **Adding core AST features**:
   - Edit [`dqs/core/analyzer.py`](../dqs/core/analyzer.py) or [`dqs/core/static_advisor.py`](../dqs/core/static_advisor.py).
   - Core changes **must stay framework-agnostic** (no Django imports!).

2. **Adding Django/DRF adapter features**:
   - Edit files in [`dqs/adapters/drf/execution/`](../dqs/adapters/drf/execution/), [`dqs/adapters/drf/routing/`](../dqs/adapters/drf/routing/), or [`dqs/adapters/drf/mocking/`](../dqs/adapters/drf/mocking/).

3. **Writing Tests**:
   - Pure logic tests go to `tests/core/test_analyzer.py` or `tests/core/test_static_advisor.py`.
   - Django integration tests go to `tests/adapters/drf/test_*.py`.

---

## 📝 Code Style & Standards

- **Formatter/Linter**: Ruff (configured in `pyproject.toml`)
- **Type Checking**: MyPy (strict mode for core, relaxed for adapters)
- **Test Framework**: Pytest with Django plugin
- **Commit Style**: Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`)

Run checks before committing:
```bash
ruff check .
ruff format .
mypy dqs/
pytest -m core
```