# Changelog

All notable changes to the **Da Profiler** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-25

### Added

- **Core AST Analyzer (`dqs.core.analyzer`)**:
  - `fingerprint(sql)`: Core SQL normalization engine powered by `sqlglot`. Strips numeric/string literals, collapses dynamic `IN (...)` parameter lists into `IN (?)`, and canonicalizes table aliases (`T0`, `T1`).
  - `detect_n_plus_one(queries, threshold)`: Aggregation logic that groups executed raw SQL queries by their AST fingerprint and flags N+1 query patterns exceeding execution thresholds.
- **Core Test Suite (`tests/core/`)**:
  - Unit test suite (`test_analyzer.py`) verifying literal stripping, `IN` clause collapsing, alias canonicalization, and threshold detection.
- **Development & Container Setup**:
  - `Dockerfile` and `docker-compose.yml` configuring an isolated development environment running Python 3.12 and PostgreSQL 16.
  - `pyproject.toml` packaging setup specifying `sqlglot>=26.0.0` as core requirement and optional `[django]` extras.
- **Documentation & Repository Infrastructure**:
  - Comprehensive `README.md` with features, dev quickstart, and step-by-step SQL-to-AST fingerprinting examples.
  - Open-source governance files: `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `ROADMAP.md`, and `CHANGELOG.md`.

---

---

## [0.1.1] - 2026-06-26

### Changed

- **Robust N+1 Grouping in `analyzer.py`**: Updated `detect_n_plus_one` to group queries by a composite key of `(SQL Fingerprint, source_location)` rather than just the AST fingerprint. This eliminates false positives where structurally identical queries originating from completely different parts of the codebase were incorrectly aggregated.
- **Prioritized Flag Sorting**: The resulting N+1 flags are now sorted by execution count in descending order, automatically surfacing the most severe database bottlenecks to the top of the UI.

### Added

- **Pinpoint Precision**: Update Detect N+1 function in analyzer.py to immediately tells developers where in their codebase the N+1 loop originates (e.g., Potential N+1 detected on table 'authors' at sample_app/views.py:38).
- **Framework Decoupled**: core/analyzer.py remains 100% agnostic accepting "source_location" key from whatever payload dqs/adapters/drf/runner.py sends.

---

## [0.2.0] - Django Introspector & Isolated Sandbox Execution

### Added
- **Django App Registration (`dqs.adapters.django.apps.DQSConfig`)**: Created an apps.py file and configured DQS as an installable Django application.
- **Route Introspector (`DjangoIntrospector.list_routes`)**: 
  - Recursively walks Django's `url_patterns` (handling nested `include()` resolvers).
  - Automatically classifies views as DRF (`APIView`/`ViewSet`) vs. standard Django views.
  - Maps allowed HTTP methods.
- **Sandbox Execution Engine (`DjangoSandboxRunner.execute_isolated`)**:
  - Executes endpoints inside a `transaction.atomic()` savepoint with guaranteed `transaction.savepoint_rollback()`.
  - Simulates HTTP requests via `RequestFactory` with direct `request.user` auth bypass.
  - Captures raw executed SQL queries and timing using `CaptureQueriesContext`.
- **Side-Effect Detection (`_detect_side_effects`)**:
  - Greps view source code using `inspect.getsource` to surface warnings for non-database side effects (`requests`, `httpx`, `smtplib`, Celery `.delay()`, Channels `group_send`).
- **Integration Test Environment (`demo_project/`)**:
  - Added relational test models (`Author`, `Book`, `Publisher`).
  - Added intentionally flawed N+1 endpoints (`NPlusOneBookListView`) for profiling validation.
- **Adapter Test Suite (`tests/adapters/drf/`)**: Added unit and integration tests covering route discovery, sandbox isolation, query capture, and transaction rollback.

## [0.2.1] - 2026-06-29

### Fixed

- **DRF ViewSet action resolution (`introspector.py`)**: The ViewSet branch of `_analyze_view()` no longer silently falls back to `methods or ["GET"]` when the `actions` mapping can't be resolved. It now returns `executable=False` with an explicit `reason_unexecutable`, matching the "skip rather than guess" behavior already applied to FBV/CBV routes. Eliminates a class of false-positive "executable" routes that would have failed silently at profile time.
- **DRF Runner Logic Syntax**: Corrected invalid boolean syntax (`&&` to `and`) in `dqs/adapters/drf/runner.py` when evaluating HTTP `Response` objects during execution profiling.
- **Pytest Configuration Case Sensitivity**: Fixed `pytest-django` initialization by declaring `DJANGO_SETTINGS_MODULE` in uppercase within `pyproject.toml`.

### Added

- **Safety guard test coverage**: Added `test_pipeline.py`, covering:
  - `DjangoIntrospector` and `DjangoSandboxRunner` both raise `ImproperlyConfigured` when `DEBUG=False`.
  - `DjangoIntrospector.list_all_routes()` returns well-formed `RouteMetadata` objects across all discovered routes.
  - `DjangoSandboxRunner.execute_isolated()` returns a `400` with a clear error message for unsupported HTTP methods.
  - `_detect_side_effects()` correctly flags risky imports (e.g. `smtplib`) in plain view functions.
  - `_extract_source_location()` correctly walks the call stack to attribute a query to user code, bypassing framework-internal frames.
  - SQL fingerprinting and `detect_n_plus_one()` — literal normalization, `AND` clause ordering, and threshold-based flagging — re-verified against the updated introspector/runner.
- **Editable Install Context in Docker**: Update the folder architecture to support demos for other orms and Move the docker file into demos/drf folder.

### Known Limitations (carried forward, not regressions)

- `_detect_side_effects()` still inspects `as_view()`'s dispatch wrapper for class-based views rather than the actual `get()`/`post()` handlers, so side-effect detection on CBVs remains unreliable. Slated to be superseded by the whole-codebase static AST advisor in v0.25.0, not patched here.
- Query capture remains `CaptureQueriesContext`-based; the DB-driver-boundary interceptor lands in v0.25.0.

## [0.25.0] - 2026-07-01 — Query Interceptor, Target Abstraction & Static AST Advisor

### Added

- **`Target` abstraction (`dqs/core/targets.py`)**: New unified dataclass (`id`, `kind`, `triggerable`, `trigger_spec`, `static_findings`) representing anything that can execute code — a view, a signal receiver, or a Celery task — under one consistent shape. This is what lets both the human-facing UX and the future MCP layer operate on one interface instead of a different code path per "kind" of triggerable code.

- **DB-driver-boundary query interceptor (`dqs/adapters/drf/query_interceptor.py`)**: New `QueryInterceptor` context manager, hooking directly into `connection.execute_wrapper()` instead of `CaptureQueriesContext`. Captures SQL, precise execution time, and — via call-stack inspection at the exact moment a query fires — the originating file/line in user code. This supersedes the request-boundary capture used since v0.2.0 and is framework-agnostic about *what* triggered the query.

- **General-purpose profiling (`DjangoSandboxRunner.profile_callable`)**: New method that runs *any* Python callable inside a transaction savepoint with the query interceptor attached, not just HTTP views. `execute_isolated()` is now one caller of `profile_callable()` — supplying "build a request, call the view" as the callable — rather than a separate, duplicated code path. Also accepts an optional `setup` callable that runs inside the same rollback boundary but *before* the interceptor attaches, so mock-data seeding is correctly excluded from captured query counts and N+1 analysis.

- **Whole-codebase static AST advisor (`dqs/core/static_advisor.py`)**: New `StaticASTAdvisor`, a pure AST scanner requiring no execution and no DB connection. Ships with two checks:
  - **ORM-call-inside-loop detection** — flags `.filter()`/`.get()`/`.all()`-style calls found inside a `for`/`async for` block as a potential N+1 pattern, independent of whether that code has any discoverable entry point at all.
  - **Blocking-call detection** — flags `requests.post`, `smtplib.SMTP`, `time.sleep`, and similar synchronous I/O calls. Resolves `import X as Y` and `from X import Y` aliasing via tracked import maps before matching, so `import requests as r; r.post(...)` and `from smtplib import SMTP; SMTP(...)` are correctly caught instead of silently bypassing detection.
  - `_detect_side_effects()` in `runner.py` now delegates to this advisor instead of its own separate keyword grep, unifying side-effect detection under one engine.

- **Target discovery engine (`dqs/adapters/drf/discovery.py`)**: New `DjangoTargetDiscovery.discover_all()`:
  - Converts previously introspected URL routes into `Target(kind="view")` records.
  - Walks Django's `post_save` / `pre_save` / `post_delete` / `pre_delete` signal registries (safely unpacking `weakref` receivers) into `Target(kind="signal")` records.
  - Walks the Celery task registry into `Target(kind="task")` records.
  - Every discovered signal and task callable is fed through `StaticASTAdvisor` via `_analyze_callable_statically()`, populating `static_findings` even for code with no URL and no execution path yet — this is what lets an agent get *something* actionable on code DQS can't trigger.

### Fixed (caught during this phase's development, before release)

- **Seed data isolation**: An early version of the `profile_callable()`/`execute_isolated()` refactor ran mock-data seeding *inside* the same block the query interceptor was attached to, which would have silently inflated query counts and could trigger false N+1 flags from seed `INSERT` statements. Corrected by routing seeding through the new `setup` parameter, which runs inside the rollback boundary but strictly before interception begins.
- **Import-alias blind spot in blocking-call detection**: Initial implementation matched blocking calls via literal string prefixes (`"requests.post"`), which missed any aliased or `from`-style import. Added `visit_Import`/`visit_ImportFrom` tracking and alias resolution so detection works regardless of import style.

### Known Limitations (explicitly deferred, not oversights)

- `DJANGO_ORM_METHODS` matches on generic method names (`get`, `filter`, `all`, `create`, etc.) — any non-Django class exposing similarly named methods and called inside a loop will currently produce a false-positive `ORM_CALL_IN_LOOP` finding.
- Schema-level checks (cross-referencing `Meta.indexes`/`db_index` against `.filter()`/`.exclude()`/`.order_by()` call sites) are not yet implemented.
- PK strategy advice (flagging auto-increment integer PKs on write-heavy models, suggesting UUIDv7) is not yet implemented.
- WebSocket/Channels consumer discovery is not yet implemented — no `Target(kind="consumer")` records are produced.
- Signals and Celery tasks are discovered and marked `triggerable=True`, but no execution path exists yet to actually synthesize a signal-triggering event or invoke a task by name from `trigger_spec` — discovery and triggerability are currently decoupled. This is the next piece of work.

## [0.25.1] - 2026-07-02

### Fixed

- **Seed data no longer pollutes query capture (`runner.py`)**: `profile_callable()` now accepts an optional `setup` callable that runs inside the same transaction/savepoint but *before* `QueryInterceptor` attaches. `execute_isolated()`'s mock-data seeding moved into this `setup` step, so seed `INSERT` queries can no longer be captured, inflate query counts, or trigger false N+1 flags on the profiled endpoint's own queries. This was a silent correctness bug affecting every `execute_isolated()` call that used `seed_count > 0`.

- **Blocking-call detection now resolves import aliases (`static_advisor.py`)**: `StaticASTAdvisor` now tracks `import X as Y` and `from X import Y` statements via new `visit_Import()`/`visit_ImportFrom()` handlers, and resolves call names through this map before matching against `BLOCKING_CALL_PREFIXES`. Previously, aliased or `from`-imports (`import requests as r; r.post(...)`, `from smtplib import SMTP; SMTP(...)`) silently bypassed detection entirely — this was an explicitly named requirement in the v0.25.0 roadmap that wasn't met in the initial implementation.

### Verified (no change needed)

- Confirmed `analyzer.py`'s `detect_n_plus_one()` never reads query timing data (`time`/`time_ms`) — it only uses `sql` and `source_location`. The `runner.py` → `analyzer.py` payload handoff is fully compatible as-is; no shim required.

### Known limitation (documented, not fixed)

- Import-alias resolution in `static_advisor.py` is single-pass and order-dependent — an import appearing *after* its use in source order won't be resolved. Not expected to matter for standard top-of-file imports.

## [0.25.1] - 2026-07-03

### Fixed

- **Seed data no longer pollutes query capture (`runner.py`)**: `profile_callable()` now accepts an optional `setup` callable that runs inside the same transaction/savepoint but *before* `QueryInterceptor` attaches. `execute_isolated()`'s mock-data seeding moved into this `setup` step, so seed `INSERT` queries can no longer be captured, inflate query counts, or trigger false N+1 flags on the profiled endpoint's own queries. This was a silent correctness bug affecting every `execute_isolated()` call that used `seed_count > 0`.

- **Blocking-call detection now resolves import aliases (`static_advisor.py`)**: `StaticASTAdvisor` now tracks `import X as Y` and `from X import Y` statements via new `visit_Import()`/`visit_ImportFrom()` handlers, and resolves call names through this map before matching against `BLOCKING_CALL_PREFIXES`. Previously, aliased or `from`-imports (`import requests as r; r.post(...)`, `from smtplib import SMTP; SMTP(...)`) silently bypassed detection entirely — this was an explicitly named requirement in the v0.25.0 roadmap that wasn't met in the initial implementation.

### Verified (no changes needed)

- **AST Normalization logic (`analyzer.py`)**: Confirmed that the core AST normalizer logic required zero modifications to support the new interceptor mechanism. SQL fingerprints and N+1 aggregations generate exactly as they did under the old boundary limits.

---

## [0.3.0] - Dynamic Path Converter Engine, Mock Data Generator & Request-Body Inference - 2026-07-14

### Added

- **Dynamic Path Converter Engine (`dqs/adapters/drf/converters.py`)**:
  - `PathConverterResolver`: Modular parameter resolution pipeline handling standard and custom Django path converters (`int`, `slug`, `uuid`, `str`, `path`).
  - Extract path parameters directly from Django `RoutePattern` instances.
  - Automatically fetch or seed target model instances via `model_bakery` to extract real database primary keys/slugs/codes for parameterized URL paths (e.g., `/books/<int:pk>/`).
  - Fallback to deterministic synthetic parameter values (`int` -> `1`, `uuid` -> `"123e4567-e89b-12d3-a456-426614174000"`, `slug` -> `"test-slug"`) when DB records are unavailable.
  - Render concrete executable URLs using Django `reverse()` with regex substitution fallbacks.

- **Schema & PK Strategy Advisor (`dqs/adapters/drf/schema_advisor.py`)**:
  - `check_pk_strategy()`: Inspects model metadata and flags auto-increment integer PKs (`AutoField`, `BigAutoField`), recommending UUIDv7 for write-heavy or distributed workloads.
  - `check_missing_indexes()`: Cross-references fields queried in `.filter()`, `.exclude()`, or `.order_by()` against model index metadata (`db_index`, `unique`, `Meta.indexes`) to flag missing index bottlenecks.

- **Signal, Celery & Consumer Discovery Updates (`dqs/adapters/drf/discovery.py`)**:
  - Integrated schema-level advisor checks (`check_pk_strategy` and `check_missing_indexes`) into URL view target discovery.
  - Added Celery background task discovery scanning `celery.current_app.tasks`.
  - Added Django Channels ASGI route discovery for WebSocket consumers (`Target(kind="consumer", triggerable=False)`).

- **Mock Data Generator Engine (`dqs/adapters/drf/mock_generator.py`)**:
  - `ModelBakeryGenerator`: Encapsulates model mock data creation with constraint-safety, uniqueness guards (`unique=True`, `unique_together`, `UniqueConstraint`), and sequence generators.
  - **Validation Recovery Flow**: Gracefully recovers from `baker` failures via optional field filling, parent relation auto-seeding, and direct fallback model instantiation.
  - **In-Memory Sample Cache**: Caches generated model instances per session/run to prevent redundant database operations.

- **Request Body Inferrer (`dqs/adapters/drf/body_inferrer.py`)**:
  - `infer_request_body()`: Automatically inspects DRF view classes, `serializer_class` definitions (or `get_serializer_class()`), and Django `form_class` definitions to produce valid mock JSON payloads for `POST`, `PUT`, and `PATCH` endpoints when `data=None`.
  - Maps serializer field types (`CharField`, `EmailField`, `SlugField`, `IntegerField`, `DecimalField`, `DateTimeField`, `ChoiceField`, `PrimaryKeyRelatedField`, `NestedSerializer`, `JSONField`) to realistic mock values.
  - Automatically integrated into `DjangoSandboxRunner.execute_isolated()`.

---

## [0.3.1] - 2026-07-16

### Fixed

- **Dynamic Path Converter Engine (`dqs/adapters/drf/converters.py`)**:
  - `PathConverterResolver`: Extracts URL path parameters and matches standard/custom converters (`int`, `slug`, `uuid`, `str`, `path`).
  - Resolves concrete parameters automatically by inspecting target models or generating mock entities via `model_bakery`.
  - Reverses parameters into valid executable URL paths for parameterized endpoints (e.g. `/api/v1/books/42/`).

- **Mock Data Generator Engine (`dqs/adapters/drf/mock_generator.py`)**:
  - `ModelBakeryGenerator`: Provides constraint-safe mock entity generation respecting `unique`, `unique_together`, and foreign key relations.
  - Features validation error recovery and an in-memory sample cache to minimize DB overhead.

- **Request Body Inferrer (`dqs/adapters/drf/body_inferrer.py`)**:
  - `infer_request_body()`: Automatically infers mock JSON payloads for `POST`, `PUT`, and `PATCH` requests by analyzing DRF serializer classes (`serializer_class`, `get_serializer_class()`) and Django form fields.

- **Schema & PK Strategy Advisor (`dqs/adapters/drf/schema_advisor.py`)**:
  - `check_pk_strategy()`: Recommends UUIDv7 over auto-increment integer PKs on high-concurrency models.
  - `check_missing_indexes()`: Flags fields used in `.filter()`, `.exclude()`, or `.order_by()` that lack database indexes (`db_index`, `Meta.indexes`).

- **Unified Target Discovery (`dqs/adapters/drf/discovery.py`)**:
  - Expanded discovery pipeline to cover URL views, signals, Celery tasks, and Channels ASGI consumers into unified `Target` records.

---
