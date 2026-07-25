# Changelog

All notable changes to the **Query Sandbox (DQS)** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] - 25/06/2026

### Added
* **Core AST Analyzer (`dqs.core.analyzer`)**:
  * `fingerprint(sql)`: Core SQL normalization engine powered by `sqlglot`. Strips numeric/string literals, collapses dynamic `IN (...)` parameter lists into `IN (?)`, and canonicalizes table aliases (`T0`, `T1`).
  * `detect_n_plus_one(queries, threshold)`: Aggregation logic that groups executed raw SQL queries by their AST fingerprint and flags N+1 query patterns exceeding execution thresholds.
* **Core Test Suite (`tests/core/`)**:
  * Unit test suite (`test_analyzer.py`) verifying literal stripping, `IN` clause collapsing, alias canonicalization, and threshold detection.
* **Development & Container Setup**:
  * `Dockerfile` and `docker-compose.yml` configuring an isolated development environment running Python 3.12 and PostgreSQL 16.
  * `pyproject.toml` packaging setup specifying `sqlglot>=26.0.0` as core requirement and optional `[django]` extras.
* **Documentation & Repository Infrastructure**:
  * Comprehensive `README.md` with features, dev quickstart, and step-by-step SQL-to-AST fingerprinting examples.
  * Open-source governance files: `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `ROADMAP.md`, and `CHANGELOG.md`.