# Testing Guide

Da Profiler uses **pytest** with a marker-based, framework-scoped test architecture. This lets the same test infrastructure scale cleanly as new adapters (SQLAlchemy, FastAPI, etc.) are added in future releases.

---

## Test Structure

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
        ├── test_converters.py       # PathConverterResolver unit tests
        ├── test_discovery.py        # Signal & task discovery tests
        ├── test_introspector.py     # URL route scanning and lookup map tests
        ├── test_query_interceptor.py# DB execute_wrapper SQL capture tests
        ├── test_runner.py           # SandboxRunner & step-driven pipeline tests
        └── test_runner_integration.py # Setup isolation & savepoint rollback test
```

---

## Marker Taxonomy

| Marker | Meaning | Requires DB? | Speed |
|---|---|---|---|
| `core` | Pure Python (dqs/core/) — no Django, no ORM | No | ⚡ Fastest |
| `django` | Django ORM + DB access (dqs/adapters/drf/) | Yes | 🐢 Slower |
| `drf` | DRF adapter subset of django tests | Yes | 🐢 Slower |
| `sqlalchemy` | Future SQLAlchemy adapter | Yes | 🐢 Slower |

---

## Running Tests

```bash
# Run everything
pytest

# Run only pure Python core tests (fastest — no DB, no Django setup)
pytest -m core

# Run only Django/DRF adapter tests
pytest -m django

# Run only DRF-specific adapter tests
pytest -m drf

# Run with verbose output
pytest -v

# Run and stop at first failure
pytest -x

# Run a specific file
pytest tests/adapters/drf/test_runner.py
```

---

## Adding a New Framework Adapter

When a new adapter is added (e.g., `dqs/adapters/sqlalchemy/`), follow this pattern:

1. **Create the adapter test directory**: `tests/adapters/sqlalchemy/`
2. **Create `conftest.py`** in that directory with `pytestmark = [pytest.mark.sqlalchemy]` and any shared fixtures.
3. **Write tests** scoped to that adapter's framework primitives only — never mix framework-specific fixtures across adapters.
4. **Tag the marker** in `pyproject.toml` under `[tool.pytest.ini_options.markers]`.

The `core` tests must **never** be modified to include framework-specific imports. If you need to test framework interaction with a core module, write the test in the appropriate adapter test directory.

---

## Shared Fixtures (DRF adapter)

These are available to all tests inside `tests/adapters/drf/` without importing:

| Fixture | Type | Description |
|---|---|---|
| `runner` | `DjangoSandboxRunner` | Pre-initialized sandbox runner |
| `introspector` | `DjangoIntrospector` | Pre-initialized URL introspector |
| `seeded_book` | `Book` | Seeded `Publisher → Author → Book` relational record |
| `enforce_debug_mode` | `autouse` | Forces `DEBUG=True` for all DRF adapter tests |

---

> **Note:** `tests/core/` tests do NOT use pytest-django and require no database or Django settings. They run with standard pytest only.
