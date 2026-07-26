# DQS — Roadmap & Build Status

*Source of truth for project execution. Tracks what is completed, currently under construction, and planned.*

---

## Current Status Overview

| Phase | Description | Status |
| :--- | :--- | :--- |
| **v0.1.0** | Infra Scaffolding & Core AST Analyzer | ✅ **COMPLETED** |
| **v0.2.0** | Django Introspector & Isolated Sandbox Execution | 🟡 **IN PROGRESS** |
| **v0.3.0** | Mock Data Generator & Validation Recovery | 🔲 **PLANNED** |
| **v0.4.0** | Interactive Dashboard & Query Visualizer | 🔲 **PLANNED** |

---

## v0.1.0 — Infra Scaffolding & Core AST Analyzer

> Status: COMPLETED ✅

**In plain words:** Build the repository scaffolding, Docker development environment, and the 100% framework-agnostic SQL AST fingerprinting and N+1 detection engine in `dqs/core/`.

### Core (`dqs/core/`)
- [x] `analyzer.py` — `fingerprint(sql)`: Uses `sqlglot` to normalize SQL statements (strips literals, collapses `IN (...)` lists, canonicalizes table aliases to `T0`, `T1`).
- [x] `analyzer.py` — `detect_n_plus_one(queries, threshold)`: Groups query logs by fingerprint and flags groups exceeding execution thresholds.
- [x] `analyzer.py` — `suggest_fix(fingerprint, relationships)`: Generates plain-English Django ORM recommendations (`.select_related()` / `.prefetch_related()`).

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

> Status: IN PROGRESS 🟡

**In plain words:** Scan the host Django app to discover all active routes, and execute an endpoint request inside a rolling-back database transaction (`transaction.atomic()` savepoint) so no mock data or side effects persist in the database.

### Django Adapter (`dqs/adapters/django/`)
- [x] `apps.py` — Register `dqs.adapters.django` as an installable Django app.
- [x] `introspector.py` — `DjangoIntrospector.list_all_routes()`: Recursively walks `url_patterns` and returns `{path, methods, view_name, view_type, is_drf, executable, has_path_params}` metadata. Excludes DQS's own `/dqs/` routes from results, enforces `DEBUG=True`, and skips routes where the HTTP methods can't be confidently determined (e.g. undecorated function-based views) rather than guessing.
- [x] `runner.py` — `DjangoSandboxRunner.execute_isolated()`:
  - Generates WSGI requests via `RequestFactory`.
  - Attaches `request.user` directly (bypassing auth middleware).
  - Captures queries using `CaptureQueriesContext(connection)`.
  - Wraps execution in `transaction.atomic()` and rolls back via `transaction.savepoint_rollback()`.
  - Enforces `DEBUG=True` and a strict HTTP-method whitelist before executing.
  - Catches exceptions raised inside the profiled view so a buggy endpoint reports as an error instead of crashing the sandbox call.
- [x] `runner.py` — Greps view source (`inspect.getsource`) for unhandled side-effects (`requests.post`, `smtplib`, Celery `.delay()`, `group_send()`) and emits warning flags.

> ⚠️ **Known integration gap, not yet resolved — carries into v0.3.0/v0.4.0:**
> `DjangoIntrospector` can discover a route like `/books/<int:pk>/` and flags it via `has_path_params: True`, but it does **not** solve how to actually call that route — `DjangoSandboxRunner.execute_isolated()` needs a concrete path (e.g. `/books/5/`), not a pattern with an unfilled converter. The likely fix is having the Dashboard/Mock Data Generator pull a real primary key from a freshly-generated mock row and substitute it into the path before calling the Runner — but that substitution logic doesn't exist anywhere yet. Tracked explicitly here so it isn't discovered as a surprise once the Dashboard (v0.4.0) tries to wire "click endpoint → run" together for any route with a dynamic URL segment.

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
- [ ] **Path-param substitution helper** — given a route flagged `has_path_params: True` by the Introspector, pull a real primary key (or other identifying field) from a freshly-generated mock row of the matching model and substitute it into the route's path pattern before it's passed to `DjangoSandboxRunner.execute_isolated()`. This is the resolution to the gap flagged in v0.2.0 above — needs to land here since this is the first point in the pipeline where a "real row with a real PK" actually exists.

**What "done" looks like:** Ask the generator for 50 `Book` instances, handle any validation errors via sample input, verify 50 rows are created during execution, and confirm `transaction.savepoint_rollback()` cleans them up completely. Additionally: successfully run the sandbox against a route like `/books/<int:pk>/` end-to-end, using a PK pulled from a generated row.

---

## v0.4.0 — Interactive Dashboard & Query Visualizer

> Status: PLANNED 🔲

**In plain words:** A server-rendered UI where developers can view routes, trigger sandbox profiling, adjust mock data counts, and inspect AST fingerprints alongside raw SQL query details.

### Core (`dqs/core/dashboard/`) & Django Adapter
- [ ] `views.py` — Endpoints to list routes, trigger sandbox execution, and return JSON payload.
- [ ] `urls.py` — Mount dashboard views under `/dqs/`.
- [ ] `templates/dqs/dashboard.html` — Server-rendered Tailwind UI featuring:
  - **Left Panel:** Discovered API endpoints list with HTTP method tags. Routes with `has_path_params: True` should be visually marked (e.g. a small "requires ID" badge) so it's clear to the user why one extra step (picking/generating a row) happens before "Run" is available for those.
  - **Right Panel:** Execution summary (Status Code, Total Time, Total Query Count).
  - **N+1 Alert Cards:** Red-highlighted boxes detailing flagged AST fingerprints and fix suggestions (`.select_related()` / `.prefetch_related()`).
  - **Query & Fingerprint Inspection Drawer:** Expandable accordions for each AST fingerprint showing:
    1. Normalized fingerprint string.
    2. Total query count & execution time.
    3. Expandable list of **all individual raw SQL statements** executed under that fingerprint with execution times.
  - **Validation Error Modal:** Form prompt asking for sample data when `model_bakery` encounters custom validation rules.

**What "done" looks like:** Open `localhost:8000/dqs/` in a browser, click an endpoint, run with 50 mock rows, view N+1 alerts, and click an AST fingerprint to inspect all underlying raw queries. For a route with a dynamic URL segment (e.g. `/books/<int:pk>/`), confirm the Dashboard transparently uses a generated row's PK rather than failing or requiring the user to manually type one in.

---

## Later Releases (v2.0+)

> Status: FUTURE 🔮

- **CLI (`dqs/cli.py`):** Interactive terminal initializer for choosing framework adapters.
- **FastAPI / SQLAlchemy Adapter:** Second concrete adapter implementation.
- **Abstract Base Classes (`BaseIntrospector`, `BaseRunner`):** Formalize contracts once adapter #2 exists.
- **Polyfactory Swap-in:** Multi-ORM generator replacing `model_bakery`.
- **OpenAPI Integration:** Route discovery via `drf-spectacular` schema parsing.
- **WebSocket / Channels execution support:** `DjangoIntrospector` can already discover Channels consumer routes (`include_websockets=True`), but they're flagged `executable: False` and hidden from the Dashboard by default — no Sandbox Runner execution path exists for them yet. Building one is a v2 task, not a v1 gap, since it needs a fundamentally different execution mechanism than `RequestFactory`.