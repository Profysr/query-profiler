# DQS — Roadmap & Build Status

*Source of truth for project execution. Tracks what is completed, currently under construction, and planned.*

---

## Current Status Overview

| Phase | Description | Status |
| :--- | :--- | :--- |
| **v0.1.0** | Infra Scaffolding & Core AST Analyzer | 🟡 **IN PROGRESS** |
| **v0.2.0** | Django Introspector & Isolated Sandbox Execution | 🔲 **PLANNED** |
| **v0.3.0** | Mock Data Generator & Validation Recovery | 🔲 **PLANNED** |
| **v0.4.0** | Interactive Dashboard & Query Visualizer | 🔲 **PLANNED** |

---

## v0.1.0 — Infra Scaffolding & Core AST Analyzer

> Status: IN PROGRESS 🟡

**In plain words:** Build the repository scaffolding, Docker development environment, and the 100% framework-agnostic SQL AST fingerprinting and N+1 detection engine in `dqs/core/`.

### Core (`dqs/core/`)
- [x] `analyzer.py` — `fingerprint(sql)`: Uses `sqlglot` to normalize SQL statements (strips literals, collapses `IN (...)` lists, canonicalizes table aliases to `T0`, `T1`).
- [x] `analyzer.py` — `detect_n_plus_one(queries, threshold)`: Groups query logs by fingerprint and flags groups exceeding execution thresholds.
- [ ] `analyzer.py` — `suggest_fix(fingerprint, relationships)`: Generates plain-English Django ORM recommendations (`.select_related()` / `.prefetch_related()`).

### Tests (`tests/core/`)
- [x] `test_analyzer.py` — Unit tests verifying literal stripping, `IN` clause collapsing, alias canonicalization, and threshold detection.

### Infra & Specs (`docs/`, root)
- [x] Repository layout (`dqs/core/`, `dqs/adapters/django/`, `tests/`)
- [x] Open-source documentation (`README.md` with ORM-to-AST breakdown, `CHANGELOG.md`, `ROADMAP.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`)
- [x] Packaging spec (`pyproject.toml` with `sqlglot>=26.0.0` and `[django]` optional extras)
- [x] Docker setup (`Dockerfile`, `docker-compose.yml` with Postgres 16)

**What "done" looks like:** `pytest tests/core/` runs completely green in Docker, proving AST normalization works against raw SQL without needing Django running yet.

---

## v0.2.0 — Django Introspector & Isolated Sandbox Execution

> Status: PLANNED 🔲

**In plain words:** Scan the host Django app to discover all active routes, and execute an endpoint request inside a rolling-back database transaction (`transaction.atomic()` savepoint) so no mock data or side effects persist in the database.

### Django Adapter (`dqs/adapters/django/`)
- [ ] `apps.py` — Register `dqs.adapters.django` as an installable Django app.
- [ ] `introspector.py` — `DjangoIntrospector.list_routes()`: Recursively walks `url_patterns` and returns `{path, method, view_name, is_drf}` metadata.
- [ ] `runner.py` — `DjangoSandboxRunner.execute_isolated()`:
  - Generates WSGI requests via `RequestFactory`.
  - Attaches `request.user` directly (bypassing auth middleware).
  - Captures queries using `CaptureQueriesContext(connection)`.
  - Wraps execution in `transaction.atomic()` and rolls back via `transaction.savepoint_rollback()`.
- [ ] `runner.py` — Greps view source (`inspect.getsource`) for unhandled side-effects (`requests.post`, `smtplib`, Celery `.delay()`) and emits warning flags.

### Demo Project (`demo_project/`)
- [ ] `demo_project/` settings, URLs, and DB configuration pointing to Postgres 16.
- [ ] `sample_app/models.py` — Test models (`Author`, `Book`, `Publisher`) with FK relationships.
- [ ] `sample_app/views.py` — Intentionally flawed endpoints (triggering N+1 queries) for integration testing.

**What "done" looks like:** Run a request through `DjangoSandboxRunner`, receive a list of executed raw SQL queries and response status, and verify via database query that 0 rows were modified or created.

---

## v0.3.0 — Mock Data Generator & Validation Recovery

> Status: PLANNED 🔲

**In plain words:** Automatically generate relational test data using `model_bakery`, with interactive recovery prompts if field validation fails.

### Django Adapter (`dqs/adapters/django/`)
- [ ] `mock_generator.py` — `ModelBakeryGenerator.generate()`: Wraps `baker.make(Model, _quantity=N)`.
- [ ] `mock_generator.py` — Validation Recovery Flow:
  - Catches `ValidationError` and `IntegrityError`.
  - Accepts a single valid user sample input for failing fields.
  - Reuses exact sample value across all N rows.
- [ ] `mock_generator.py` — Uniqueness Guard: Detects `unique=True` on failing fields and falls back to generating 1 row with an explanatory notice.
- [ ] `mock_generator.py` — In-Memory Sample Cache: Caches user-provided sample values in memory keyed by `model_name.field_name` to avoid duplicate prompts during local server sessions.

**What "done" looks like:** Ask the generator for 50 `Book` instances, handle any validation errors via sample input, verify 50 rows are created during execution, and confirm `transaction.savepoint_rollback()` cleans them up completely.

---

## v0.4.0 — Interactive Dashboard & Query Visualizer

> Status: PLANNED 🔲

**In plain words:** A server-rendered UI where developers can view routes, trigger sandbox profiling, adjust mock data counts, and inspect AST fingerprints alongside raw SQL query details.

### Core (`dqs/core/dashboard/`) & Django Adapter
- [ ] `views.py` — Endpoints to list routes, trigger sandbox execution, and return JSON payload.
- [ ] `urls.py` — Mount dashboard views under `/dqs/`.
- [ ] `templates/dqs/dashboard.html` — Server-rendered Tailwind UI featuring:
  - **Left Panel:** Discovered API endpoints list with HTTP method tags.
  - **Right Panel:** Execution summary (Status Code, Total Time, Total Query Count).
  - **N+1 Alert Cards:** Red-highlighted boxes detailing flagged AST fingerprints and fix suggestions (`.select_related()` / `.prefetch_related()`).
  - **Query & Fingerprint Inspection Drawer:** Expandable accordions for each AST fingerprint showing:
    1. Normalized fingerprint string.
    2. Total query count & execution time.
    3. Expandable list of **all individual raw SQL statements** executed under that fingerprint with execution times.
  - **Validation Error Modal:** Form prompt asking for sample data when `model_bakery` encounters custom validation rules.

**What "done" looks like:** Open `localhost:8000/dqs/` in a browser, click an endpoint, run with 50 mock rows, view N+1 alerts, and click an AST fingerprint to inspect all underlying raw queries.

---

## Later Releases (v2.0+)

> Status: FUTURE 🔮

- **CLI (`dqs/cli.py`):** Interactive terminal initializer for choosing framework adapters.
- **FastAPI / SQLAlchemy Adapter:** Second concrete adapter implementation.
- **Abstract Base Classes (`BaseIntrospector`, `BaseRunner`):** Formalize contracts once adapter #2 exists.
- **Polyfactory Swap-in:** Multi-ORM generator replacing `model_bakery`.
- **OpenAPI Integration:** Route discovery via `drf-spectacular` schema parsing.