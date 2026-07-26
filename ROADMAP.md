# DQS — Roadmap & Build Status

*Source of truth for project execution. Tracks what is completed, currently under construction, and planned — and, in this section, why any of it matters.*

---

## North Star — What We're Actually Building

**The one-sentence version:** DQS turns "why is this endpoint slow?" from a manual, browser-clicking investigation into something an AI coding agent (or a human) can ask, get a precise answer to, fix, and instantly re-verify — with zero risk to the developer's real database.

**The end state, concretely:**
- A developer (or their AI agent) runs one command / one MCP tool call against a Django project.
- DQS discovers every endpoint on its own — no manual registration, no clicking through the app first.
- It executes any endpoint — including ones with dynamic URL segments like `/books/<int:pk>/` — safely, using auto-generated mock data, entirely inside a transaction that's rolled back the instant it's done. The developer's actual database is never touched.
- It reports back not just "here are 40 queries," but "here's the exact line causing 38 of them, and here's the one-line fix."
- An AI agent can close the loop itself: detect the N+1, apply the suggested `.select_related()`, then call DQS again to confirm the query count actually dropped — without a human re-testing anything by hand.

**Why this order (v0.1 → v1.0):** each phase only becomes buildable once the one before it exists. You can't safely execute an endpoint (v0.2) before you can find it (v0.1's analyzer exists independently, but the Introspector needed for discovery is v0.2). You can't profile a realistic app (v0.3) until execution works and there's data to generate. You can't offer an agent anything meaningful (v0.4) until profiling actually produces a trustworthy, structured result. The CLI/dashboard (v1.0) is deliberately last and explicitly optional — the agentic loop is the core product; a terminal command and a browser UI are convenience layers on top of it, not the other way around.

**A guiding rule for whoever picks up any task below:** if you're ever unsure whether something belongs in v1 scope, ask "does this get us closer to a trustworthy, zero-risk profiling result an agent can act on?" If yes, it's in scope. If it's about polish, multi-framework support, or a nicer UI, it's very likely a "Later Release" item further down this file — check there before building it early.

---

## Why the Django/Python version floors are what they are

`pyproject.toml` currently specifies `django>=4.2` and `python>=3.10`, with no upper ceiling. This is a **deliberate reach decision, not a stability one** — worth stating plainly since it's the opposite tradeoff of "pin to the newest LTS for predictability":

- The goal is the widest possible adoption across the existing Django community without maintaining compatibility shims for versions old enough to require special-casing.
- 4.2/3.10 is treated as the boundary before which supporting older ORM/typing behavior would meaningfully slow down development. Everything at or after that line is fair game; anything before it is explicitly out of scope, and no one should spend time making DQS work on Django 3.x or Python 3.9.
- The tradeoff being accepted: an open floor means a fresh install could resolve onto whatever the newest Django release is at install time, including one that later turns out to have breaking changes for DQS. That's accepted risk here, not an oversight — if it ever actually breaks something, that's the moment to add a ceiling, not before.

---

## Current Status Overview

| Phase | Description | Status |
| :--- | :--- | :--- |
| **v0.1.0** | Infra Scaffolding & Core AST Analyzer | ✅ **COMPLETED** |
| **v0.2.0** | Django Introspector & Isolated Sandbox Execution | 🟡 **IN PROGRESS** |
| **v0.3.0** | Dynamic Path Converter Engine & Mock Data Generator | 🔲 **PLANNED** |
| **v0.4.0** | Model Context Protocol (MCP) Server & Agentic Loop | 🔲 **PLANNED** |
| **v1.0.0** | Terminal CLI Linter & Interactive Dashboard (optional) | 🔲 **FUTURE** |

---

## v0.1.0 — Infra Scaffolding & Core AST Analyzer

> Status: COMPLETED ✅

**In plain words:** Build the repository scaffolding, Docker development environment, and the 100% framework-agnostic SQL AST fingerprinting and N+1 detection engine in `dqs/core/`. This is the piece every later phase depends on — it has to work correctly and in isolation before anything gets layered on top.

### Core (`dqs/core/`)
- [x] `analyzer.py` — `fingerprint(sql)`: uses `sqlglot` to normalize SQL statements (strips literals, collapses `IN (...)` lists, canonicalizes table aliases to `T0`, `T1`, sorts safe AND-chains).
- [x] `analyzer.py` — `detect_n_plus_one(queries, threshold)`: groups query logs by fingerprint and flags groups exceeding the execution threshold (default 3).
- [x] `analyzer.py` — `suggest_fix(fingerprint, relationships)`: generates plain-English Django ORM recommendations (`.select_related()` / `.prefetch_related()`).

### Tests (`tests/core/`)
- [x] `test_analyzer.py` — unit tests verifying literal stripping, `IN` clause collapsing, alias canonicalization, and threshold detection.

### Infra & Specs (`docs/`, root)
- [x] Repository layout (`dqs/core/`, `dqs/adapters/django/`, `tests/`)
- [x] Open-source documentation (`README.md`, `CHANGELOG.md`, `ROADMAP.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`)
- [x] Packaging spec (`pyproject.toml` — `sqlglot>=26.0.0` core dep, `[django]` optional extra, floors explained above)
- [x] Docker setup (`Dockerfile`, `docker-compose.yml` with Postgres 16)

**What "done" looks like:** `pytest tests/core/` runs completely green in Docker, proving AST normalization works against raw SQL without needing Django running at all.

---

## v0.2.0 — Django Introspector & Isolated Sandbox Execution

> Status: IN PROGRESS 🟡

**In plain words:** Scan the host Django app to discover all active routes, and execute an endpoint request inside a rolling-back database transaction so no mock data or side effects persist. This is the phase that proves DQS can safely touch a real Django project at all.

### Django Adapter (`dqs/adapters/django/`)
- [x] `apps.py` — registers `dqs.adapters.django` as an installable Django app.
- [x] `introspector.py` — `DjangoIntrospector.list_all_routes()`: recursively walks `url_patterns`, returns `{path, methods, view_name, view_type, is_drf, executable, has_path_params}` metadata. Excludes DQS's own `/dqs/` routes, enforces `DEBUG=True`, and skips routes where HTTP methods can't be confidently determined rather than guessing.
- [x] `runner.py` — `DjangoSandboxRunner.execute_isolated()`:
  - Generates WSGI requests via `RequestFactory`.
  - Attaches `request.user` directly (bypassing auth middleware entirely).
  - Captures queries via `CaptureQueriesContext(connection)`.
  - Wraps execution in `transaction.atomic()`, rolls back via `transaction.savepoint_rollback()`.
  - Enforces `DEBUG=True` and a strict HTTP-method whitelist before executing.
  - Catches exceptions raised inside the profiled view so a buggy endpoint reports as an error instead of crashing the sandbox call.
- [x] `runner.py` — greps view source (`inspect.getsource`) for unhandled side-effects (`requests.post`, `smtplib`, Celery `.delay()`, `group_send()`) and emits warning flags.
- [ ] **Enriched execution payload** — wrap execution in timing blocks to return a structured result, not just raw queries and status:
  ```json
  {
    "route": "/books/12/",
    "status_code": 200,
    "metrics": {
      "total_time_ms": 14.2,
      "db_time_ms": 8.7,
      "total_queries": 12,
      "unique_fingerprints": 3
    },
    "n_plus_one_detected": true,
    "analysis": [ /* fingerprint groups + suggest_fix() output from dqs/core/analyzer.py */ ]
  }
  ```
  This is what turns the Runner's current raw-queries-and-status-code return value into something an MCP tool call (v0.4.0) can hand back to an agent as a single benchmarkable result — the agent needs `total_queries`/`db_time_ms` as a before/after number to confirm a fix actually worked.

> ⚠️ **Known integration gap, carries into v0.3.0:**
> `DjangoIntrospector` can discover a route like `/books/<int:pk>/` and flags it via `has_path_params: True`, but nothing yet substitutes a real value in — `DjangoSandboxRunner.execute_isolated()` needs a concrete path (`/books/5/`), not a pattern with an unfilled converter. This is v0.3.0's `converters.py` + Mock Data Generator work. Tracked here so it isn't a surprise once anything downstream tries to actually run a dynamic-URL route end to end.

### Demo Project (`demo_project/`)
- [ ] `demo_project/` settings, URLs, and DB configuration pointing to Postgres 16.
- [ ] `sample_app/models.py` — test models (`Author`, `Book`, `Publisher`) with FK relationships.
- [ ] `sample_app/views.py` — intentionally flawed endpoints (triggering N+1 queries) for integration testing.

**What "done" looks like:** run a request through `DjangoSandboxRunner`, get back the full enriched payload (queries, timing, fingerprints, suggestions), and confirm via direct database query that 0 rows were modified or created.

---

## v0.3.0 — Dynamic Path Converter Engine & Mock Data Generator

> Status: PLANNED 🔲

**In plain words:** Teach DQS to handle real-world routes that aren't bare paths, and to invent realistic-but-safe test data so those routes have something valid to run against. This is the phase where DQS goes from "works on toy endpoints" to "works on the messy routes a real Django app actually has."

### Django Adapter (`dqs/adapters/django/`)
- [ ] `converters.py` — parses `pattern.pattern.converters` to detect `int`, `str`, `slug`, and `uuid` path converters on a given route (`IntConverter`, `UUIDConverter`, `SlugConverter`/`StringConverter`). Build this first — it's self-contained, testable without any mock data existing yet, and both `mock_generator.py` and the path substitution helper below depend on knowing the converter type before they can do anything.
- [ ] `converters.py` — **Model resolution**, two-step: (1) for class-based/DRF views, inspect `view_class.queryset.model` or `view_class.model` directly; (2) for FBVs or views without an explicit model attribute, fall back to matching route tokens against `django.apps.apps.get_models()` (e.g. `/books/` → `Book`). **This fallback is a heuristic and will guess wrong sometimes** — consistent with the "skip rather than guess" principle already used in the Introspector, if resolution is ambiguous or fails, this must surface a clear error asking for an explicit override rather than silently generating mock data for the wrong model.
- [ ] `mock_generator.py` — `ModelBakeryGenerator.generate()`: wraps `baker.make(Model, _quantity=N)`.
- [ ] `mock_generator.py` — Validation Recovery Flow: catch `ValidationError`/`IntegrityError`, accept one valid sample entry from the user, reuse that exact value across all N rows rather than guessing at the validator's pattern.
- [ ] `mock_generator.py` — Uniqueness Guard: detect `unique=True` on a failing field and fall back to generating exactly 1 row, with an explanatory note rather than a silent failure.
- [ ] `mock_generator.py` — In-Memory Sample Cache: keyed by `model_name.field_name`, so an accepted sample isn't re-prompted for on every subsequent run in the same dev server session.
- [ ] **Path substitution helper** — resolves the v0.2.0 gap: given a route flagged `has_path_params: True`, pull a real primary key (or other resolved value) from a freshly-generated mock row of the matching model, and substitute it into the route before it's passed to `execute_isolated()`. If a custom/unrecognized converter is involved, allow an explicit override (`path_params={"pk": 42}`) instead of guessing.

**What "done" looks like:** ask the generator for 50 `Book` instances, handle any validation errors via the sample-entry flow, confirm 50 rows exist mid-run and `savepoint_rollback()` removes all of them afterward. Additionally: successfully profile a route like `/books/<int:pk>/` end to end, using a PK pulled from a generated row rather than a manually supplied one.

---

## v0.4.0 — Model Context Protocol (MCP) Server & Agentic Loop

> Status: PLANNED 🔲

**In plain words:** This is the phase that delivers on the actual point of the project — turning everything built in v0.1–v0.3 into something an AI coding agent can call directly, act on, and re-verify, without a human relaying information back and forth by hand.

### MCP Layer (`dqs/mcp/`)
- [ ] `server.py` — native MCP server implementation using the standard `mcp` SDK (stdio and/or SSE transport).
- [ ] **MCP Tools:**
  - `list_django_routes()` — returns the same structured metadata `DjangoIntrospector.list_all_routes()` produces, exposed as an agent-callable tool.
  - `profile_endpoint(route, method, path_params=None)` — runs the Sandbox Runner (using the v0.3.0 path-substitution logic when `path_params` isn't supplied) and returns the enriched payload from v0.2.0's execution work: timing, query count, AST fingerprints, fix suggestions.
  - `seed_mock_data(model_name, quantity)` — exposes the Mock Data Generator directly, so an agent can prepare sandbox state ahead of a profiling call rather than relying on `profile_endpoint` to do it implicitly every time.
- [ ] **MCP Resources & Prompts** — expose a standard context prompt (e.g. `fix_n_plus_one`) so an agent has explicit guidance on how to interpret a DQS fingerprint result and what a correct rewrite looks like, rather than inferring it from the raw JSON alone.

**What "done" looks like:** an AI IDE agent (Claude, Cursor, etc.) connects to the DQS MCP server, calls `list_django_routes`, picks one, calls `profile_endpoint`, receives a fingerprinted N+1 result with a fix suggestion, rewrites the view itself, calls `profile_endpoint` again on the same route, and confirms the query count actually dropped (e.g. 50 → 2) — all without a human doing anything except approving the agent's changes.

---

## v1.0.0 — Terminal CLI Linter & Interactive Dashboard (optional)

> Status: FUTURE 🔮

**In plain words:** Convenience layers for people who want to use DQS without an AI agent in the loop — a CLI for scripted/CI use, and a browser dashboard for anyone who'd rather click around visually. Neither is required for the core agentic loop to work; both are built on top of the same v0.1–v0.4 engine, not a replacement for it.

- [ ] `dqs/cli.py` — a `dqs scan` / `dqs check --max-queries-per-route=N` terminal command for local developer checks and CI/CD quality gates (e.g. fail a build if a new endpoint introduces an N+1).

  > 🤔 **Open sequencing question:** this is currently placed after the MCP server (v0.4.0), purely because it's a "convenience layer built on the core engine." But the CI/CD gate doesn't actually depend on the MCP layer at all — it only needs v0.1–v0.3. It's also one of the strongest differentiators for the large majority of Django developers who aren't using an AI agent day-to-day. Worth a deliberate decision on whether `dqs check` should be pulled forward and shipped in parallel with v0.4.0 rather than strictly after it, rather than leaving it here by default.
- [ ] `dqs/dashboard/` — an optional local server-rendered UI (endpoint list, run button, N+1 alerts, fingerprint inspection drawer) for developers who prefer a visual dashboard over AI chat integration. This was originally scoped as the core v0.4.0 deliverable in an earlier draft of this roadmap — it's still planned, just intentionally after the MCP/agentic loop rather than before it, since that loop is the actual differentiator.

---

## Later Releases (v2.0+)

> Status: FUTURE 🔮

- **FastAPI / SQLAlchemy Adapter** — second concrete framework adapter.
- **Abstract Base Classes (`BaseIntrospector`, `BaseRunner`)** — formalize adapter contracts once adapter #2 actually exists to generalize from; deliberately not written speculatively against a single implementation.
- **Polyfactory swap-in** — multi-ORM mock data generator, replacing `model_bakery` once a second ORM adapter needs it.
- **OpenAPI integration** — route discovery via `drf-spectacular` schema parsing, as an alternative/supplement to `DjangoIntrospector`'s own URL-tree walk.
- **WebSocket / Channels execution support** — `DjangoIntrospector` can already discover Channels consumer routes (`include_websockets=True`), flagged `executable: False` and hidden by default, since no Sandbox Runner execution path exists for them yet. A fundamentally different execution mechanism than `RequestFactory` is needed here — genuinely v2 scope, not a v1 gap.