# Query Sandbox (DQS) 🔍

> The Agentic ORM Profiler & Performance Orchestrator for Django.

`Query Sandbox` (DQS) discovers your Django project's endpoints automatically, executes them in isolated, self-rolling-back transactions, and detects N+1 queries using AST-based SQL fingerprinting — then hands the result to an AI coding agent (or a human) as a prescriptive, copy-pasteable ORM fix.

> ⚠️ **Note on scope:** this README reflects an active pivot from an earlier dashboard-first design toward an agent-first (MCP) design. If you're looking for the previous plain server-rendered dashboard direction, that's now a v1.0.0 optional feature rather than the core v0.4.0 deliverable — see [Roadmap](#project-status--roadmap).

---

## Table of Contents

- [Why DQS](#why-dqs)
- [How DQS Compares](#how-dqs-compares)
- [Key Features](#key-features)
- [How It Works: From Query to Fix Suggestion](#how-it-works-from-query-to-fix-suggestion)
- [Dynamic Route Resolution](#dynamic-route-resolution)
- [The Agentic Loop (MCP)](#the-agentic-loop-mcp)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Quickstart](#quickstart-development-environment)
- [Running Tests](#running-tests)
- [Project Status & Roadmap](#project-status--roadmap)
- [Contributing](#contributing)

---

## Why DQS

Traditional profilers (Django Silk, Django Debug Toolbar) are reactive and human-dependent — you have to click through your app to generate traffic, then manually read through logged SQL to spot a bottleneck. DQS flips that:

1. **Proactive discovery** — scans your Django URL tree automatically. No manual clicking required to generate the endpoint list.
2. **Zero DB footprint** — every profiling run happens inside a `transaction.atomic()` savepoint and rolls back immediately after. Nothing persists.
3. **Prescriptive fixes** — uses `sqlglot` AST parsing to normalize queries and output the exact `.select_related()` / `.prefetch_related()` call to add, not just a raw query dump.
4. **Agent-first** — exposes an MCP server so AI coding agents (Claude, Cursor, Windsurf) can autonomously profile an endpoint, detect N+1s, rewrite the view, and re-verify the fix in a closed loop.

---

## How DQS Compares

| Feature | Django Silk | DQS |
|---|---|---|
| Discovery | Passive — only logs URLs you physically hit | Active — scans the URL tree automatically |
| Database overhead | High — persists request/response logs to your DB | Zero — runs entirely via rollback |
| N+1 detection | Manual inspection of logged SQL | Automated AST fingerprinting (`sqlglot`) |
| Output | Raw SQL + timing | Prescriptive ORM fix + enriched metrics |
| CI/automation | Difficult to run headlessly | Built for CLI, pytest, and agent workflows |
| AI agent integration | None | Native MCP server (stdio / SSE) |

---

## Key Features

- **Zero-trace sandbox** — profiles queries inside `transaction.atomic()` savepoints, rolled back automatically after every run.
- **AST-based fingerprinting** — `sqlglot` parses SQL into an AST, strips literals, normalizes table aliases, and collapses `IN (...)` clauses of any length into one shape.
- **Dynamic route resolution** — profiles routes with path converters (`/books/<int:pk>/`) by generating a real mock row and substituting a concrete value automatically.
- **Actionable fix suggestions** — flags queries repeated 3+ times with the same fingerprint and suggests the exact ORM fix.
- **Agentic MCP server** — lets an AI IDE agent call `list_django_routes`, `profile_endpoint`, and `seed_mock_data` directly, closing the loop from detection to fix to re-verification without a human in the middle.
- **Extensible by design** — a framework-agnostic core (`dqs/core/`) stays fully decoupled from Django-specific code (`dqs/adapters/django/`).

---

## How It Works: From Query to Fix Suggestion

### Example — Classic Foreign Key N+1

**1. The unoptimized view**

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
SELECT "id", "title", "author_id" FROM "sample_app_book";
SELECT "id", "name" FROM "sample_app_author" WHERE "id" = 10;
SELECT "id", "name" FROM "sample_app_author" WHERE "id" = 25;
SELECT "id", "name" FROM "sample_app_author" WHERE "id" = 42;
```

> Simplified for readability — Django's actual `CaptureQueriesContext` output table-qualifies every column (e.g. `"sample_app_author"."id"`). The fingerprinting logic handles both forms identically.

**3. DQS normalizes them to one fingerprint**

`dqs.core.analyzer.fingerprint()` parses each query with `sqlglot`, replacing the changing literal (`10`, `25`, `42`) with a placeholder, so all three collapse to:

```sql
SELECT "id", "name" FROM "sample_app_author" WHERE "id" = ?
```

**4. DQS flags it**

```json
{
  "fingerprint": "SELECT \"id\", \"name\" FROM \"sample_app_author\" WHERE \"id\" = ?",
  "count": 3,
  "suggestion": "Add .select_related('author') to your QuerySet."
}
```

**5. The fix**

```python
books = Book.objects.select_related('author').all()
```

Same AST engine also collapses variable-length `IN (...)` clauses (`IN (1,2)` and `IN (1,2,3,4,5)` both fingerprint to `IN (?)`) — a naive regex-based normalizer can't do this reliably, since it has no concept of the expression's structure.

---

## Dynamic Route Resolution

Many real endpoints look like `/books/<int:pk>/hash/<uuid:hash>/`, not a bare path. DQS resolves these in three steps before it can actually call the route:

```
1. Introspect Path Converters
   Reads pattern.pattern.converters (Int, UUID, Slug, ...)
        │
        ▼
2. Resolve Target Django Model
   Inspects view_class.queryset.model or URL token hints
        │
        ▼
3. Inject Concrete Parameters
   Generates a temporary mock row -> substitutes real values
   (e.g. /books/12/hash/9f2b.../)
```

If a route uses a custom converter DQS can't confidently resolve, an explicit override can be passed instead of guessing — via the MCP tool call (`path_params={"pk": 42}`) or the equivalent Python-level call, rather than DQS silently assuming a value.

---

## The Agentic Loop (MCP)

```
AI IDE Agent (Cursor/Claude)
   │
   ├─ 1. list_django_routes()            → discovers endpoints
   ├─ 2. profile_endpoint(route, method)  → runs the sandbox, captures queries
   ├─ 3. AST fingerprint + fix suggestion → returned as enriched JSON
   ├─    [ Agent rewrites views.py ]
   └─ 4. profile_endpoint(...) again      → verifies query count dropped (e.g. 50 → 2)
```

This closes the loop end-to-end: an agent can detect a bottleneck, apply the suggested `.select_related()`/`.prefetch_related()` fix itself, and immediately re-run the same profiling call to confirm the fix actually worked — without a human manually re-testing in a browser.

---

## Architecture

```
dqs/
├── core/                  # Framework-agnostic — analyzer, fingerprinting. Never imports Django.
│   └── analyzer.py
├── adapters/
│   └── django/            # All Django-specific code lives here only.
│       ├── introspector.py    # discovers routes, classifies CBV/DRF/FBV
│       ├── runner.py          # isolated, rolled-back execution
│       ├── converters.py      # dynamic path-param resolution
│       └── mock_generator.py  # model_bakery wrapper + validation recovery
└── mcp/
    └── server.py           # MCP server exposing DQS as agent-callable tools

demo_project/                # Throwaway Django project used only for local dev/testing.
                              # Not shipped as part of the package.
```

**The rule that matters most:** `dqs/core/` never imports anything from `dqs/adapters/`. This one-way boundary is what lets a second framework adapter (or the MCP layer itself) build on top of the analysis engine without ever needing to modify it.

---

## Requirements

- Docker & Docker Compose (v2 syntax)
- No local Python install required for development

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
docker compose run --rm web django-admin startproject demo_project .

# 4. Start the full stack
docker compose up -d

# 5. Run migrations
docker compose exec web python manage.py migrate

# 6. Create a superuser
docker compose exec web python manage.py createsuperuser
```

**Day-to-day commands:**

```bash
docker compose up -d           # start everything
docker compose logs -f web     # tail app logs
docker compose exec web bash   # shell into the running container
docker compose down            # stop everything (-v also wipes the DB volume)
```

---

## Running Tests

```bash
docker compose run --rm web pytest
```

```
tests/
├── test_analyzer.py       # dqs/core/analyzer.py — pure functions, no Django needed
├── test_introspector.py   # dqs/adapters/django/introspector.py
└── test_runner.py         # dqs/adapters/django/runner.py — needs the demo_project DB
```

---

## Project Status & Roadmap

| Phase | Description | Status |
|---|---|---|
| v0.1.0 | Infra Scaffolding & Core AST Analyzer | ✅ Completed |
| v0.2.0 | Django Introspector & Isolated Sandbox Execution | 🟡 In Progress |
| v0.3.0 | Dynamic Path Converter Engine & Mock Data Generator | 🔲 Planned |
| v0.4.0 | Model Context Protocol (MCP) Server & Agentic Loop | 🔲 Planned |
| v1.0.0 | Terminal CLI Linter & Interactive Dashboard (optional) | 🔲 Future |

Full detail, file-by-file, lives in [`ROADMAP.md`](./ROADMAP.md). The reasoning behind each architectural decision — including why certain things were deliberately left out of earlier versions — lives in [`CHANGELOG.md`](./CHANGELOG.md).

---

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for setup steps, coding standards, and the PR process. The short version: respect the `core`/`adapters` boundary, run `pytest` before opening a PR, and check `ROADMAP.md`/`CHANGELOG.md` before touching fingerprinting logic or adding a new adapter.

## License

MIT — see [`LICENSE`](./LICENSE). 