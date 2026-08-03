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
| [`dqs/core/analyzer.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/core/analyzer.py) | **SQL AST Fingerprinting & N+1 Detection**: Uses `sqlglot` to parse raw SQL into Abstract Syntax Trees, strip dynamic numeric/string literals, collapse `IN (...)` clauses, and canonicalize table aliases. Functions: `fingerprint()`, `detect_n_plus_one()`, `suggest_fix()`. |
| [`dqs/core/static_advisor.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/core/static_advisor.py) | **Static AST Analyzer**: Pure AST scanner that inspects user Python source code without execution. Detects ORM queries inside `for`/`async for` loops and flags blocking synchronous I/O (`requests`, `smtplib`, `time.sleep`) resolving import aliases (`import X as Y`, `from X import Y`). |
| [`dqs/core/targets.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/core/targets.py) | **Target Data Model**: Defines the unified `Target` dataclass (`id`, `kind`, `triggerable`, `trigger_spec`, `static_findings`) unifying views, signals, Celery tasks, and consumers under a single schema. |

---

### 2. Django & DRF Adapter (`dqs/adapters/drf/`)

| File | Primary Purpose & Key Functions |
| :--- | :--- |
| [`dqs/adapters/drf/apps.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/adapters/drf/apps.py) | **Django AppConfig**: Registers Da Profiler as a Django app (`dqs.adapters.drf`). Enforces safety check on startup ensuring `settings.DEBUG == True`. |
| [`dqs/adapters/drf/discovery.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/adapters/drf/discovery.py) | **Target Discovery Engine**: `DjangoTargetDiscovery.discover_all()` recursively finds Django URL endpoints, signal receivers (`post_save`, `pre_save`, `post_delete`), and registered Celery tasks, feeding each through `StaticASTAdvisor`. |
| [`dqs/adapters/drf/introspector.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/adapters/drf/introspector.py) | **URL Pattern Introspector**: `DjangoIntrospector.list_all_routes()` recursively walks Django's `urlpatterns` tree, classifying endpoints as DRF `ViewSet`, `APIView`, FBV, or CBV. Safely reports `executable=False` when routes cannot be statically resolved. |
| [`dqs/adapters/drf/query_interceptor.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/adapters/drf/query_interceptor.py) | **DB Driver Boundary Interceptor**: Context manager hooking into Django's `connection.execute_wrapper()`. Captures executed SQL, exact duration, and walks `inspect.stack()` to attribute queries to user code line numbers. |
| [`dqs/adapters/drf/runner.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/adapters/drf/runner.py) | **Sandbox Execution Engine**: `DjangoSandboxRunner.profile_callable()` and `execute_isolated()`. Runs HTTP requests inside `transaction.atomic()` savepoints with guaranteed `savepoint_rollback()`. Handles pre-profiling setup for mock data seeding. |
| [`dqs/adapters/drf/schema_advisor.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/adapters/drf/schema_advisor.py) | **Schema & Index Advisor**: Analyzes Django ORM models and fields to suggest database indexing strategies. |

---

### 3. Demo Application (`demos/drf/`)

| File | Primary Purpose |
| :--- | :--- |
| [`demos/drf/sample_app/models.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/demos/drf/sample_app/models.py) | Sample relational models (`Author`, `Book`, `Publisher`) used for integration testing. |
| [`demos/drf/sample_app/views.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/demos/drf/sample_app/views.py) | Intentionally flawed endpoints (e.g. `NPlusOneBookListView`) used to test and validate Da Profiler's N+1 detection. |
| [`demos/drf/config/urls.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/demos/drf/config/urls.py) | Root URL resolver mapping sample app routes. |

---

### 4. System & Project Configuration Files

| File | Primary Purpose |
| :--- | :--- |
| [`pyproject.toml`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/pyproject.toml) | Packaging configuration, dependencies (`sqlglot>=26.0.0`), optional extras (`[django]`, `[dev]`), and pytest configuration. |
| [`architecture.md`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/architecture.md) | Technical architecture document, component sequence diagrams, and design principles. |
| [`README.md`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/README.md) | Primary project homepage, feature highlights, and dev quickstart. |
| [`ROADMAP.md`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/ROADMAP.md) | Version roadmap tracking completed phases (v0.1, v0.2, v0.25) and planned phases (v0.3, v0.4 MCP, v1.0). |
| [`CHANGELOG.md`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/CHANGELOG.md) | Historical record of changes, additions, fixes, and architectural revisions. |
| [`CONTRIBUTING.md`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/CONTRIBUTING.md) | Guidelines for opening issues, writing PRs, coding standards, and running tests. |

---

## 🛠️ Setting Up Your Local Environment

```bash
# 1. Clone repository
git clone https://github.com/your-org/da-profiler.git
cd da-profiler

# 2. Start PostgreSQL & Dev Container
docker compose build
docker compose up -d

# 3. Run Pytest Suite
docker compose exec <service_name e.g demo-django> pytest
```

---

## 🎯 How to Add New Features

1. **Adding core AST features**:
   - Edit [`dqs/core/analyzer.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/core/analyzer.py) or [`dqs/core/static_advisor.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/core/static_advisor.py).
   - Core changes **must stay framework-agnostic**.

2. **Adding Django/DRF adapter features**:
   - Edit [`dqs/adapters/drf/runner.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/adapters/drf/runner.py) or [`dqs/adapters/drf/discovery.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/adapters/drf/discovery.py).

3. **Writing Tests**:
   - Pure logic tests go to `tests/test_analyzer.py`.
   - Django integration tests go to `tests/test_introspector.py` or `tests/test_runner.py`.
