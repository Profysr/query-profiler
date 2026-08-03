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
| **v0.2.0** | Django Introspector & Isolated Sandbox Execution | ✅ **COMPLETED** |
| **v0.25.0** | Query Interceptor, `Target` Abstraction & Static AST Advisor | ✅ **COMPLETED** |
| **v0.3.0** | Dynamic Path Converter Engine, Mock Data Generator & Request-Body Inference | 🟡 **IN PROGRESS** |
| **v0.4.0** | Model Context Protocol (MCP) Server & Agentic Loop | 🔲 **PLANNED** |
| **v1.0.0** | Terminal CLI Linter & Interactive Dashboard (optional) | 🔲 **FUTURE** |

---

## v0.1.0 — Infra Scaffolding & Core AST Analyzer

> Status: COMPLETED ✅

- [x] `analyzer.py` — `fingerprint(sql)`, `detect_n_plus_one(queries, threshold)`, `suggest_fix(fingerprint, relationships)`.
- [x] `test_analyzer.py` — unit tests for literal stripping, `IN` clause collapsing, alias canonicalization, threshold detection.
- [x] Repository layout, docs, packaging spec, Docker setup.

---

## v0.2.0 — Django Introspector & Isolated Sandbox Execution

> Status: COMPLETED ✅ 

### Django Adapter (`dqs/adapters/django/`)
- [x] `apps.py` — registers `dqs.adapters.django`, hard `DEBUG=True` guardrail in `ready()`.
- [x] `introspector.py` — `DjangoIntrospector.list_all_routes()`: recursively walks `url_patterns`, returns route metadata. Excludes `/dqs/` routes, enforces `DEBUG=True`.
- [x] `introspector.py` — FBV and CBV cases correctly return `executable=False` + `reason_unexecutable` when methods can't be statically resolved, rather than guessing.
- [x] `introspector.py` — DRF ViewSet case (Case A) now matches the "skip, don't guess" behavior already applied to FBV/CBV.
- [x] `runner.py` — `DjangoSandboxRunner.execute_isolated()`: builds WSGI requests via `RequestFactory`, wraps execution in `transaction.atomic()`.
- [x] `runner.py` — `execute_isolated()` now accepts an explicit `user` parameter.

### Demo Project (`demo_project/`)
- [x] `demo_project/` settings, URLs, Postgres 16 config.
- [x] `sample_app/models.py` — `Author`, `Book`, `Publisher` with FK relationships.
- [x] `sample_app/views.py` — intentionally flawed endpoints for integration testing.

---

## v0.25.0 — Query Interceptor, `Target` Abstraction & Static AST Advisor

> Status: COMPLETED ✅ 

### Core (`dqs/core/`)
- [x] `targets.py` — new `Target` dataclass: `id`, `kind` (`"view" | "signal" | "task" | "consumer" | "static_only"`), `triggerable: bool`, `trigger_spec: dict | None`, `static_findings: list`.
- [x] `static_advisor.py` — whole-project AST scanner (framework-agnostic, no execution, no DB connection required):
  - [x] ORM-call-inside-loop detection.
  - [ ] Schema-level checks (*deferred to future phase as noted in known limitations*).
  - [ ] PK strategy advice (*deferred to future phase*).
  - [x] Blocking-call detection.

### Django Adapter (`dqs/adapters/django/`)
- [x] `query_interceptor.py` — wraps `connection.execute_wrapper()`. Captures `(sql, duration, origin_file, origin_function, origin_line)` per query by walking `inspect.stack()`.
- [x] `runner.py` — refactored `execute_isolated()` to use `query_interceptor`; added new general-purpose `profile_callable(fn, *args, **kwargs)`.
- [x] Signal-receiver discovery — walked `Signal.receivers` to populate `Target(kind="signal")`.
- [x] Celery task discovery — walked `celery.app.tasks` registry to populate `Target(kind="task")`.
- [ ] WebSocket/Channels consumer discovery — (*deferred to v2.0+ scope*).

---

## v0.3.0 — Dynamic Path Converter Engine, Mock Data Generator & Request-Body Inference

> Status: IN PROGRESS 🟡 

### Django Adapter (`dqs/adapters/django/`)
- [ ] `converters.py` — parses `pattern.pattern.converters` to detect `int`, `str`, `slug`, `uuid` path converters.
- [ ] `converters.py` — model resolution: explicit `view_class.queryset.model`/`view_class.model` first, FBV token-matching fallback.
- [ ] `mock_generator.py` — `ModelBakeryGenerator.generate()`, Validation Recovery Flow, Uniqueness Guard, In-Memory Sample Cache.
- [ ] **Path substitution helper** — pulls a real PK from a generated mock row and substitutes it into a `has_path_params: True` route.
- [ ] **Request-body inference** — for POST/PUT/PATCH targets, read the view's `serializer_class` or `form_class` to determine expected field names/types to auto-populate `data=`.

---

## v0.35.0 — Single-Target Testing UX ("Postman-like" experience)

> Status: PLANNED 🔲

- [ ] CLI/browser selector over `list_all_routes()` / the broader `Target` list.
- [ ] This UX and the MCP tools in v0.4.0 call the *same* underlying functions.

---

## v0.4.0 — Model Context Protocol (MCP) Server & Agentic Loop

> Status: PLANNED 🔲

### MCP Layer (`dqs/mcp/`)
- [ ] `server.py` — native MCP server (`mcp` SDK, stdio and/or SSE transport).
- [ ] **MCP Tools**: `list_targets`, `get_static_findings`, `profile_target`, `seed_mock_data`.
- [ ] **MCP Resources & Prompts** — a standard context prompt (e.g. `fix_n_plus_one`).

---

## v1.0.0 — Terminal CLI Linter & Interactive Dashboard (optional)

> Status: FUTURE 🔮

- [ ] `dqs/cli.py` — `dqs scan` / `dqs check --max-queries-per-route=N`, now also able to gate on static findings.
- [ ] `dqs/dashboard/` — optional local UI (target list, run button, N+1 alerts, static findings panel, fingerprint inspection drawer).

---

## Later Releases (v2.0+)

> Status: FUTURE 🔮

- **FastAPI / SQLAlchemy Adapter** — second concrete framework adapter.
- **Abstract Base Classes (`BaseIntrospector`, `BaseRunner`, `BaseInterceptor`)** — formalize adapter contracts once adapter #2 actually exists to generalize from.
- **Polyfactory swap-in** — multi-ORM mock data generator.
- **OpenAPI integration** — route discovery via `drf-spectacular` schema parsing as a supplement to `DjangoIntrospector`'s own tree walk (note: v0.3.0 already borrows the *serializer-introspection* idea from Spectacular for request-body inference — this later item is specifically about using Spectacular's schema as an alternate discovery source, a narrower and separate thing).
- **WebSocket / Channels execution support** — discovery exists as of v0.25 (`Target(kind="consumer", triggerable=False)`), but no execution path. A fundamentally different trigger mechanism than `RequestFactory`/direct-call is needed — genuinely v2 scope.