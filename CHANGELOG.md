# Changelog

All notable changes to the **Query Sandbox (DQS)** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

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
- **Framework Decoupled**: core/analyzer.py remains 100% agnostic accepting "source_location" key from whatever payload dqs/adapters/django/runner.py sends.

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
- **Adapter Test Suite (`tests/adapters/django/`)**: Added unit and integration tests covering route discovery, sandbox isolation, query capture, and transaction rollback.

## [0.2.0] - 2026-06-29

### Fixed
- **DRF Runner Logic Syntax**: Corrected invalid boolean syntax (`&&` to `and`) in `dqs/adapters/drf/runner.py` when evaluating HTTP `Response` objects during execution profiling.
- **Pytest Configuration Case Sensitivity**: Fixed `pytest-django` initialization by declaring `DJANGO_SETTINGS_MODULE` in uppercase within `pyproject.toml`.
- **Editable Install Context in Docker**: Update the folder architecture to support demos for other orms and Move the docker file into demos/drf folder.