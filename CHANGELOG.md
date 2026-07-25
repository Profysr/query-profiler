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
- **Pinpoint Precision**: Update Detect N+1 function in analyzer.py to immediately tells developers where in their codebase the N+1 loop originates (e.g., Potential N+1 detected on table 'authors' at sample_app/views.py:38).
- **Framework Decoupled**: core/analyzer.py remains 100% agnostic accepting "source_location" key from whatever payload dqs/adapters/django/runner.py sends.

---
