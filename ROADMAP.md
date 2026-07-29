# DQS — Roadmap & Build Status

*Source of truth for project execution. Tracks what is completed, currently under construction, and planned — and, in this section, why any of it matters.*

> **Revision note (this update):** This roadmap incorporates a structural pivot agreed after v0.2.0 was mostly built: DQS moves from "discover a route → simulate a request → capture queries" to "intercept every query at the DB-driver boundary → walk the call stack to find its origin." This eliminates the need to separately discover signals, Celery tasks, and service-layer functions as distinct "kinds" of thing DQS has to know about — anything that runs, however it was triggered, gets seen. See the new **v0.25** phase below for the mechanism, and the new **`Target`** abstraction that unifies views/signals/tasks/consumers under one interface for both the human-facing UX and the MCP layer.

---

## North Star — What We're Actually Building

**The one-sentence version:** DQS turns "why is this endpoint slow, and what else in this codebase is quietly writing bad queries or doing something risky?" from a manual, browser-clicking investigation into something an AI coding agent (or a human) can ask, get a precise answer to, fix, and instantly re-verify — with zero risk to the developer's real database.

**The end state, concretely:**
- A developer (or their AI agent) runs one command / one MCP tool call against a Django project.
- DQS discovers every endpoint on its own — no manual registration, no clicking through the app first — and, separately, can see every query the project issues **regardless of what triggered it**: a view, a signal receiver, a Celery task, a notification service with no URL at all.
- It executes any endpoint — including ones with dynamic URL segments like `/books/<int:pk>/` — safely, using auto-generated mock data, entirely inside a transaction that's rolled back the instant it's done. The developer's actual database is never touched.
- It reports back not just "here are 40 queries," but "here's the exact file and line that issued 38 of them, and here's the one-line fix" — and, independent of whether that code was even reachable through a URL, flags risky patterns (blocking external calls, missing indexes, weak PK strategy) via static analysis.
- An AI agent can close the loop itself: detect the N+1, apply the suggested `.select_related()`, then call DQS again to confirm the query count actually dropped — without a human re-testing anything by hand.

**Why this order (v0.1 → v1.0):** each phase only becomes buildable once the one before it exists. The interceptor (v0.25) is inserted here — after basic execution works (v0.2), before mock data (v0.3) — because it changes *how* queries get captured, and every later phase (mock data profiling, MCP tool results) should be built against the final capture mechanism, not the one about to be replaced. The static AST pass and the `Target` abstraction are pulled forward alongside it because they're what let v0.4's MCP layer expose one consistent tool surface instead of a different tool per "kind" of triggerable code.

**A guiding rule for whoever picks up any task below:** if you're ever unsure whether something belongs in v1 scope, ask "does this get us closer to a trustworthy, zero-risk profiling result an agent can act on?" If yes, it's in scope. If it's about polish, multi-framework support, or a nicer UI, it's very likely a "Later Release" item further down this file — check there before building it early.

---

## Why the Django/Python version floors are what they are

`pyproject.toml` currently specifies `django>=4.2` and `python>=3.10`, with no upper ceiling. This is a **deliberate reach decision, not a stability one**:

- The goal is the widest possible adoption across the existing Django community without maintaining compatibility shims for versions old enough to require special-casing.
- 4.2/3.10 is treated as the boundary before which supporting older ORM/typing behavior would meaningfully slow down development.
- The tradeoff being accepted: an open floor means a fresh install could resolve onto whatever the newest Django release is at install time, including one that later turns out to have breaking changes for DQS. That's accepted risk here, not an oversight — if it ever actually breaks something, that's the moment to add a ceiling, not before.

---

## Current Status Overview

| Phase | Description | Status |
| :--- | :--- | :--- |
| **v0.1.0** | Infra Scaffolding & Core AST Analyzer | ✅ **COMPLETED** |
| **v0.2.0** | Django Introspector & Isolated Sandbox Execution | 🟡 **IN PROGRESS** (execution model changing — see v0.25) |
| **v0.25.0** | Query Interceptor, `Target` Abstraction & Static AST Advisor | 🔲 **NEW — PLANNED** |
| **v0.3.0** | Dynamic Path Converter Engine, Mock Data Generator & Request-Body Inference | 🔲 **PLANNED** (scope expanded) |
| **v0.4.0** | Model Context Protocol (MCP) Server & Agentic Loop | 🔲 **PLANNED** (now built on `Target`, not `RouteMetadata`) |
| **v1.0.0** | Terminal CLI Linter & Interactive Dashboard (optional) | 🔲 **FUTURE** |

---

## v0.1.0 — Infra Scaffolding & Core AST Analyzer

> Status: COMPLETED ✅ — unchanged, no scope impact from this revision.

- [x] `analyzer.py` — `fingerprint(sql)`, `detect_n_plus_one(queries, threshold)`, `suggest_fix(fingerprint, relationships)`.
- [x] `test_analyzer.py` — unit tests for literal stripping, `IN` clause collapsing, alias canonicalization, threshold detection.
- [x] Repository layout, docs, packaging spec, Docker setup.

**What "done" looks like:** `pytest tests/core/` runs green in Docker, proving AST normalization works without Django running at all.

---

## v0.2.0 — Django Introspector & Isolated Sandbox Execution

> Status: IN PROGRESS 🟡 — retained for the view-discovery and single-request execution path; the *capture mechanism* inside the Runner is being replaced in v0.25, not extended here.

### Django Adapter (`dqs/adapters/django/`)
- [x] `apps.py` — registers `dqs.adapters.django`, hard `DEBUG=True` guardrail in `ready()`.
- [x] `introspector.py` — `DjangoIntrospector.list_all_routes()`: recursively walks `url_patterns`, returns route metadata. Excludes `/dqs/` routes, enforces `DEBUG=True`.
- [x] `introspector.py` — FBV and CBV cases correctly return `executable=False` + `reason_unexecutable` when methods can't be statically resolved, rather than guessing.
- [x] `introspector.py` — DRF ViewSet case (Case A) now matches the "skip, don't guess" behavior already applied to FBV/CBV: if `actions` resolves empty, returns `executable=False` with an explicit `reason_unexecutable`, instead of silently falling back to `methods or ["GET"]`.
- [x] `runner.py` — `DjangoSandboxRunner.execute_isolated()`: builds WSGI requests via `RequestFactory`, wraps execution in `transaction.atomic()` + `transaction.savepoint()`/`savepoint_rollback()` (corrected — savepoints now open inside an active atomic block), enforces `DEBUG=True` and an HTTP-method whitelist, catches exceptions raised inside the profiled view.
- [x] `runner.py` — `execute_isolated()` now accepts an explicit `user` parameter (defaults to `AnonymousUser`) instead of hardcoding anonymous access — needed for profiling auth-gated endpoints.
- [~] `runner.py` — query capture currently via `CaptureQueriesContext(connection)`, fingerprinted correctly via `core.analyzer.fingerprint()` (fixed — no longer dedupes on raw SQL text). **This entire capture mechanism is superseded by the interceptor in v0.25** — kept here only as the "walking skeleton" proof that discover → execute → analyze → suggest works end to end for one `Target` kind (views) before generalizing.
- [~] `runner.py` — `_detect_side_effects()` exists and greps source for risky patterns, but only works reliably for plain functions, not CBVs (it inspects the `as_view()` dispatch wrapper, not the actual `get()`/`post()` handlers). **Superseded by the whole-codebase static AST advisor in v0.25**, which resolves the real view class and isn't scoped only to URL-reachable code in the first place.

### Demo Project (`demo_project/`)
- [ ] `demo_project/` settings, URLs, Postgres 16 config.
- [ ] `sample_app/models.py` — `Author`, `Book`, `Publisher` with FK relationships.
- [ ] `sample_app/views.py` — intentionally flawed endpoints for integration testing.

**What "done" looks like:** run a request through `DjangoSandboxRunner`, get back queries + timing + fingerprints + suggestions, confirm via direct DB query that 0 rows were modified or created.

---

## v0.25.0 — Query Interceptor, `Target` Abstraction & Static AST Advisor *(new phase)*

> Status: PLANNED 🔲

**In plain words:** This is the phase that answers "how do we catch N+1s and risky code in a notification service, a signal receiver, or anything else with no URL, without building a separate discovery system for every kind of trigger?" Two mechanisms, both framework-agnostic in intent:

1. **Intercept at the DB-driver boundary**, not at the request boundary — every query issued by *any* code path passes through one hook, and the Python call stack at that moment tells you exactly which function issued it.
2. **Scan the whole codebase statically**, not just URL-reachable code — catches risky patterns and schema-level issues in code that never executes during a profiling run at all.

### Core (`dqs/core/`)
- [ ] `targets.py` — new `Target` dataclass: `id`, `kind` (`"view" | "signal" | "task" | "consumer" | "static_only"`), `triggerable: bool`, `trigger_spec: dict | None`, `static_findings: list`. This becomes the one shape both the human-facing UX and the MCP layer operate on, regardless of what kind of code is behind it. Adapters populate it; `core/` never needs to know Django-specific detail about *how* a view differs from a signal.
- [ ] `static_advisor.py` — whole-project AST scanner (framework-agnostic, no execution, no DB connection required):
  - ORM-call-inside-loop detection (`.objects.get()`/`related.all()` inside a `for`/comprehension without a preceding `select_related`/`prefetch_related` on the parent queryset) — catches N+1 shape in code with zero discoverable entry point.
  - Schema-level checks: cross-reference `Meta.indexes` / `db_index` against actual `.filter()`/`.exclude()`/`.order_by()` call sites to flag missing indexes on hot columns.
  - PK strategy advice: flag auto-increment integer PKs on models that look write-heavy/distributed-friendly, suggest UUIDv7 with rationale (sortable, index-friendly, unlike UUIDv4).
  - Blocking-call detection: resolves actual imports (not string-grep) to catch `import requests as r; r.post(...)` style indirection; classifies whether the call site is inside a view (flag as blocking-in-request-cycle) vs. inside a Celery task (fine, already offloaded).
  - Output: populates `static_findings` on any `Target`, including ones with `triggerable=False`.

### Django Adapter (`dqs/adapters/django/`)
- [ ] `query_interceptor.py` — wraps `connection.execute_wrapper()`. Captures `(sql, duration, origin_file, origin_function, origin_line)` per query by walking `inspect.stack()` at capture time and finding the first frame outside `django.db.*`. This is the mechanism that lets DQS attribute an N+1 to a specific line of application code, regardless of whether that code was reached via a URL, a signal, or a direct function call.
- [ ] `runner.py` — refactor `execute_isolated()` to use `query_interceptor` instead of `CaptureQueriesContext`; add a new general-purpose `profile_callable(fn, *args, **kwargs)` that opens the interceptor + savepoint, calls *any* Python callable, and returns captured queries with origin data. `execute_isolated()` becomes one caller of `profile_callable()` (supplying "build a request, call the view" as the callable) rather than a separate code path.
- [ ] Signal-receiver discovery — walk `Signal.receivers` (e.g. `post_save`, `pre_delete`) to populate `Target(kind="signal", triggerable=True, trigger_spec={...})`, where `trigger_spec` describes how to synthesize a triggering model event (e.g. create a throwaway instance inside the same rolled-back transaction).
- [ ] Celery task discovery — walk `celery.app.tasks` registry to populate `Target(kind="task", ...)`; triggering calls the task function directly in-process (not via the broker) so it runs inside the same interceptor + rollback.
- [ ] WebSocket/Channels consumer discovery — populate as `Target(kind="consumer", triggerable=False)` for now; static findings still apply even though no execution path exists yet (execution remains v2.0+ scope, see Later Releases).

**What "done" looks like:** run the interceptor across a scripted flow that touches a view *and* a signal-triggered notification service with no URL; get back correctly attributed N+1 fingerprints for both, plus static findings (e.g. a missing index, a blocking `requests.post` call inside a view) for code that never executed at all during the run.

---

## v0.3.0 — Dynamic Path Converter Engine, Mock Data Generator & Request-Body Inference

> Status: PLANNED 🔲 — core scope unchanged from prior draft; one addition below.

### Django Adapter (`dqs/adapters/django/`)
- [ ] `converters.py` — parses `pattern.pattern.converters` to detect `int`, `str`, `slug`, `uuid` path converters.
- [ ] `converters.py` — model resolution: explicit `view_class.queryset.model`/`view_class.model` first, FBV token-matching fallback against `get_models()` second. Ambiguous resolution surfaces an explicit-override error rather than guessing (consistent with the "skip rather than guess" rule already applied elsewhere).
- [ ] `mock_generator.py` — `ModelBakeryGenerator.generate()`, Validation Recovery Flow, Uniqueness Guard, In-Memory Sample Cache — all as previously scoped.
- [ ] **Path substitution helper** — pulls a real PK from a generated mock row and substitutes it into a `has_path_params: True` route before it hits the Runner.
- [ ] *(New)* **Request-body inference** — for POST/PUT/PATCH targets, read the view's `serializer_class` (DRF) or `form_class` (plain Django) to determine expected field names/types — the same principle `drf-spectacular` uses to generate example payloads from a serializer, applied here to auto-populate `data=` for `execute_isolated()`/`profile_callable()` instead of requiring the caller to hand-type a JSON body. Feeds directly into `mock_generator.py` for realistic field values. This is what makes the "Postman-like" single-target testing experience (below) actually usable without manual payload construction.

**What "done" looks like:** generate 50 `Book` instances, handle validation errors via the sample-entry flow, confirm rollback removes them. Additionally: profile `/books/<int:pk>/` end to end using a generated PK, and profile a POST endpoint end to end using an auto-inferred request body, both without manual input.

---

## v0.35.0 — Single-Target Testing UX ("Postman-like" experience) *(new, small phase)*

> Status: PLANNED 🔲

**In plain words:** Let a human — or an agent — pick exactly one `Target` (a view, later a signal or task) from the full discovered list and run just that one, instead of re-scanning everything. This is a thin layer over v0.2/v0.25/v0.3 work, not new discovery or execution logic.

- [ ] CLI/browser selector over `list_all_routes()` / the broader `Target` list once v0.25 lands — pick one, run it, see the enriched result (queries, timing, fingerprints, fix suggestion, static findings).
- [ ] This UX and the MCP tools in v0.4.0 call the *same* underlying functions — no duplicated logic between "human clicks a button" and "agent calls a tool."

**What "done" looks like:** a developer opens the target list, selects one view, runs it, and sees the same structured result an MCP tool call would return.

---

## v0.4.0 — Model Context Protocol (MCP) Server & Agentic Loop

> Status: PLANNED 🔲 — now explicitly built on the `Target` abstraction from v0.25, not directly on `RouteMetadata`.

### MCP Layer (`dqs/mcp/`)
- [ ] `server.py` — native MCP server (`mcp` SDK, stdio and/or SSE transport).
- [ ] **MCP Tools**, all thin wrappers over the `Target` API (no per-kind special-casing at the MCP layer itself):
  - `list_targets(kind=None)` — returns all discovered targets (views today; signals/tasks once v0.25's discovery lands), optionally filtered by kind.
  - `get_static_findings(target_id)` — always available, even for `triggerable=False` targets (e.g. the notification service, WebSocket consumers) — this is what lets an agent get *something* actionable on code DQS can't yet execute.
  - `profile_target(target_id, **trigger_args)` — runs `profile_callable()` under the hood; only meaningful when `triggerable=True`.
  - `seed_mock_data(model_name, quantity)` — exposes the Mock Data Generator directly.
- [ ] **MCP Resources & Prompts** — a standard context prompt (e.g. `fix_n_plus_one`) so an agent has explicit guidance on interpreting a fingerprint result and what a correct rewrite looks like.

**What "done" looks like:** an AI agent connects, calls `list_targets`, calls `profile_target` on one, gets a fingerprinted N+1 with a fix suggestion *and* any static findings for related non-executable code (e.g. "this view's save also triggers a signal-based notification service with a blocking `smtplib` call — consider offloading it"), rewrites the view, re-profiles, confirms the query count dropped — without a human relaying anything by hand.

---

## v1.0.0 — Terminal CLI Linter & Interactive Dashboard (optional)

> Status: FUTURE 🔮 — unchanged in substance; static AST advisor (v0.25) makes `dqs check` meaningfully stronger since it can now fail a CI build on static findings alone, without needing a live DB or a running server.

- [ ] `dqs/cli.py` — `dqs scan` / `dqs check --max-queries-per-route=N`, now also able to gate on static findings (missing indexes, blocking calls) independent of dynamic profiling.
  > Open sequencing question retained from prior draft: whether to pull this forward in parallel with v0.4.0 rather than strictly after it. The static-only mode (v0.25) makes the case for pulling it forward stronger, since `dqs check --static-only` needs none of v0.2–v0.4's execution machinery.
- [ ] `dqs/dashboard/` — optional local UI (target list, run button, N+1 alerts, static findings panel, fingerprint inspection drawer).

---

## Later Releases (v2.0+)

> Status: FUTURE 🔮

- **FastAPI / SQLAlchemy Adapter** — second concrete framework adapter.
- **Abstract Base Classes (`BaseIntrospector`, `BaseRunner`, `BaseInterceptor`)** — formalize adapter contracts once adapter #2 actually exists to generalize from.
- **Polyfactory swap-in** — multi-ORM mock data generator.
- **OpenAPI integration** — route discovery via `drf-spectacular` schema parsing as a supplement to `DjangoIntrospector`'s own tree walk (note: v0.3.0 already borrows the *serializer-introspection* idea from Spectacular for request-body inference — this later item is specifically about using Spectacular's schema as an alternate discovery source, a narrower and separate thing).
- **WebSocket / Channels execution support** — discovery exists as of v0.25 (`Target(kind="consumer", triggerable=False)`), but no execution path. A fundamentally different trigger mechanism than `RequestFactory`/direct-call is needed — genuinely v2 scope.