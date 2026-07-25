# Query Sandbox 🔍

> Real-time endpoint query profiling, N+1 detection, and automated ORM fix suggestions for Django & DRF.

`Query Sandbox` (DQS) is an installable Django app that inspects your project's endpoints, executes them in isolated, self-rolling-back database transactions, and detects N+1 queries using AST-based SQL fingerprinting.

---

## Table of Contents

- [Key Features](#key-features)
- [How It Works](#how-it-works-from-query-to-fix-suggestion)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Quickstart](#quickstart-development-environment)
- [Running Tests](#running-tests)
- [Project Status](#project-status)
- [Contributing](#contributing)

---

## Key Features

- **Zero-trace sandbox** — profiles queries inside `transaction.atomic()` savepoints and rolls them back automatically. No persistent database changes, no separate test database needed.
- **AST-based fingerprinting** — uses `sqlglot` to parse SQL into an AST, strip literals, normalize table aliases, and collapse `IN (...)` clauses of any length into one shape — instead of fragile regex matching.
- **Smart mock data generation** — uses `model_bakery` to auto-populate models (including foreign keys), with an interactive recovery prompt when a field's custom validation can't be auto-generated.
- **Actionable fix suggestions** — flags queries repeated 3+ times with the same fingerprint and suggests the exact `.select_related()` / `.prefetch_related()` fix.
- **Extensible by design** — a framework-agnostic core (`dqs/core/`) is fully decoupled from framework-specific code (`dqs/adapters/django/`), so support for other frameworks can be added without touching the core analysis engine.

---

## How It Works: From Query to Fix Suggestion

### Example 1 — Classic Foreign Key N+1

**1. The unoptimized view**

A view loops over books and accesses each book's related author:

```python
# sample_app/views.py
from django.http import JsonResponse
from .models import Book

def list_books(request):
    books = Book.objects.all()  # Query #1
    data = [
        {"title": book.title, "author": book.author.name}  # Queries #2, #3, #4...
        for book in books
    ]
    return JsonResponse(data, safe=False)
```

**2. The raw SQL Django actually runs**

```sql
-- Query #1: fetch all books
SELECT "id", "title", "author_id"
FROM "sample_app_book";

-- Query #2 (Book 1 -> Author 10)
SELECT "id", "name"
FROM "sample_app_author" WHERE "id" = 10;

-- Query #3 (Book 2 -> Author 25)
SELECT "id", "name"
FROM "sample_app_author" WHERE "id" = 25;

-- Query #4 (Book 3 -> Author 42)
SELECT "id", "name"
FROM "sample_app_author" WHERE "id" = 42;
```

> **Note:** simplified for readability. Django's actual `CaptureQueriesContext` output table-qualifies every column (e.g. `"sample_app_author"."id"` rather than just `"id"`). if you're comparing this to real output, expect the longer form. The fingerprinting logic handles both identically.

**3. DQS normalizes them to one fingerprint**

`dqs.core.analyzer.fingerprint()` parses each query with `sqlglot` and replaces the changing literal (`10`, `25`, `42`) with a placeholder:

| Raw SQL | Normalized fingerprint |
|---|---|
| `... WHERE "id" = 10` | `SELECT "id", "name" FROM "sample_app_author" WHERE "id" = ?` |
| `... WHERE "id" = 25` | *(same as above)* |
| `... WHERE "id" = 42` | *(same as above)* |

**4. DQS flags it**

Because the same fingerprint ran 3+ times, DQS reports it:

```json
{
  "fingerprint": "SELECT \"id\", \"name\" FROM \"sample_app_author\" WHERE \"id\" = ?",
  "count": 3,
  "suggestion": "Add .select_related('author') to your QuerySet.",
  "queries": [
    {"sql": "SELECT ... WHERE id = 10", "time": "0.0012"},
    {"sql": "SELECT ... WHERE id = 25", "time": "0.0011"},
    {"sql": "SELECT ... WHERE id = 42", "time": "0.0009"}
  ]
}
```

**5. The fix**

```python
# One query instead of four
books = Book.objects.select_related('author').all()
```

---

### Example 2 — Variable-length `IN (...)` clauses

Different requests can pass different numbers of IDs into a filter:

```python
# Request A — 2 IDs
Tag.objects.filter(id__in=[1, 2])

# Request B — 5 IDs
Tag.objects.filter(id__in=[10, 20, 30, 40, 50])
```

These produce SQL that a naive regex-based normalizer would treat as two *different* queries (different placeholder counts):

```sql
-- Query A
SELECT "id", "name"
FROM "sample_app_tag" WHERE "id" IN (1, 2);

-- Query B
SELECT "id", "name"
FROM "sample_app_tag" WHERE "id" IN (10, 20, 30, 40, 50);
```

DQS's AST-based normalizer collapses the entire `IN (...)` list to a single placeholder regardless of length, so both queries resolve to the same fingerprint:

```sql
SELECT "id", "name" FROM "sample_app_tag" WHERE "id" IN (?)
```

This is the exact gap that plain regex normalization can't close, variable-length lists need AST-level handling to group correctly.

---

## Architecture

```
dqs/
├── core/              # Framework-agnostic — analyzer, dashboard. Never imports Django.
│   ├── analyzer.py    # fingerprinting + N+1 detection
│   └── dashboard/      # views, urls, templates
└── adapters/
    └── django/         # All Django-specific code lives here only.
        ├── introspector.py    # discovers routes
        ├── runner.py          # isolated, rolled-back execution
        └── mock_generator.py  # model_bakery wrapper + validation recovery flow

demo_project/            # Throwaway Django project used only for local dev/testing. Not shipped as part of the package — it exists so there's somewhere to install `dqs.adapters.django` and click around while developing DQS itself.
```

**The one rule that matters most in this codebase:** `dqs/core/` never imports anything from `dqs/adapters/`. `adapters/` may import from `core/`, never the other way around. This one-way boundary is what makes a second framework adapter (FastAPI/SQLAlchemy, most likely) additive later, rather than a rewrite of the analysis engine.

If you're picking up a task and unsure which folder your change belongs in, ask: *"does this code know what Django is?"* If yes → `adapters/django/`. If no → `core/`.

---

## Requirements

- Docker & Docker Compose (v2 syntax — `docker compose`, not `docker-compose`)
- That's it. No local Python install is needed — the dev environment runs entirely in containers, including the Django scaffolding step below.

---

## Quickstart (Development Environment)

```bash
# 1. Clone and set up environment variables
git clone <repo-url> && cd django-query-sandbox
cp .env.example .env

# 2. Build the image and start Postgres
docker compose build
docker compose up -d db

# 3. First-time only: scaffold the demo Django project
#    (skip this if demo_project/manage.py already exists)
docker compose run --rm web django-admin startproject demo_project .

# 4. Start the full stack
docker compose up -d

# 5. Run migrations
docker compose exec web python manage.py migrate

# 6. Create a superuser (needed for testing auth-gated endpoints)
docker compose exec web python manage.py createsuperuser

# 7. Open the dashboard
# http://localhost:8000/dqs/
```

**Day-to-day commands once set up:**

```bash
docker compose up -d           # start everything
docker compose logs -f web     # tail app logs
docker compose exec web bash   # shell into the running container
docker compose down            # stop everything (add -v to also wipe the DB volume)
```

The `web` service mounts the repo as a volume, so editing any `.py` file in `dqs/` or `demo_project/` on your host reflects immediately in the container — no rebuild needed unless you change a dependency in `pyproject.toml`.

---

## Running Tests

```bash
docker compose run --rm web pytest
```

Tests live in `tests/`, mirroring the structure of `dqs/`:

```
tests/
├── test_analyzer.py       # tests dqs/core/analyzer.py — pure functions, no Django needed
├── test_introspector.py   # tests dqs/adapters/django/introspector.py
└── test_runner.py         # tests dqs/adapters/django/runner.py — needs the demo_project DB
```

If you're adding fingerprinting logic, `test_analyzer.py` is the fastest feedback loop — it has no Django dependency and doesn't need the database running.

---

## Project Status

DQS is under active early development. See:

- **[`ROADMAP.md`](./ROADMAP.md)** — what's built, what's next, and which files each version touches.
- **[`CHANGELOG.md`](./CHANGELOG.md)** — the reasoning behind each architectural decision made so far. Worth reading before touching `core/analyzer.py` or the adapter boundary — several non-obvious tradeoffs (why `model_bakery` over `factory_boy`, why no ABCs yet, why `sqlglot` over regex) are explained there.

---

## Contributing

1. Check `ROADMAP.md` for the current version in progress — that's the active scope.
2. Respect the `core`/`adapters` boundary described in [Architecture](#architecture) above. A PR that imports Django inside `dqs/core/` will be asked to move that code.
3. New fingerprinting edge cases (subqueries, `OR`-clause handling, etc.) are welcome, but check the "punted to v2" notes in `CHANGELOG.md` first — some are deliberate scope cuts, not oversights.
4. Run `pytest` before opening a PR. `test_analyzer.py` should stay Django-free — if a test there suddenly needs Django, that's a signal something leaked across the boundary.

---