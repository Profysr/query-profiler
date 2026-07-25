# Django Query Sandbox (DQS) — V1 Build Spec

*Baseline architecture for the coding agent — v2, revised with fingerprinting, mock-data, and adapter refinements*

## Scope of V1

Django + DRF only. One database backend to start: **PostgreSQL**. No CLI framework-picker yet — that's v2, but v1's module structure is built so the CLI can slot in cleanly later (see §1.3). No docs-library integration yet — that's v2, and it'll consume an existing OpenAPI schema (drf-spectacular) rather than building our own.

V1 answers one question well: *"If I hit this endpoint, what does it do to my database?"*

---

## 1. Architecture — Four Components

```
┌─────────────────┐     ┌──────────────────┐     ┌───────────────────┐
│  Introspector    │────▶│  Sandbox Runner   │────▶│  Analyzer          │
│  (find routes)   │     │  (mock + execute) │     │  (fingerprint +    │
└─────────────────┘     └──────────────────┘     │   N+1 detect)      │
                                                    └─────────┬─────────┘
                                                              ▼
                                                    ┌───────────────────┐
                                                    │  Dashboard (UI)    │
                                                    └───────────────────┘
```

Ship as a standalone installable Django app (`pip install django-query-sandbox`, added to `INSTALLED_APPS`), not a fork of the user's project. It mounts its own URLs under `/dqs/` in dev only (guard with `if settings.DEBUG`).

### 1.1 Module layout — one module per framework/ORM

Even though v1 only ships Django support, structure the codebase so a framework is a swappable unit from day one:

```
dqs/
├── core/
│   ├── analyzer.py          # 100% framework-agnostic — only touches dicts of {sql, time}
│   └── dashboard/            # views + templates, talks to core.analyzer only
├── adapters/
│   └── django/
│       ├── introspector.py   # DjangoIntrospector
│       ├── runner.py         # DjangoSandboxRunner
│       └── mock_generator.py # ModelBakeryGenerator
└── cli.py                    # v2: picks which adapters/* module to load
```

**Rule for v1:** `core/` never imports anything from `adapters/django/`. `adapters/django/` can import from `core/`. This one-way dependency is what makes the future CLI trivial — it just decides which adapter module to import at startup, nothing in `core/` needs to change.

**No abstract base classes yet.** Don't write `BaseIntrospector(ABC)` / `BaseSandboxRunner(ABC)` until a second adapter (e.g. SQLAlchemy/FastAPI) is actually being built. With only one concrete implementation, an ABC is a guess at a contract — and FastAPI's async, dependency-injected request lifecycle won't map cleanly onto whatever shape we guess today. Keep the Django adapter as a plain class with clearly named public methods (`list_routes`, `execute_isolated`, `generate_mock_data`); formalize the contract when adapter #2 shows what's actually shared.

---

### 1.2 Introspector

**Job:** list endpoints without the user writing anything.

- Walk `django.urls.get_resolver().url_patterns` recursively (handles `include()` nesting).
- For each resolved pattern, grab the view class and its allowed HTTP methods (`view.cls.http_method_names` for DRF `APIView`/`ViewSet` subclasses).
- Detect DRF vs. plain Django view by checking `isinstance(view.cls, APIView)` — plain Django views only get GET/POST support in v1, DRF views get full CRUD.

**Punt to v2:** parsing custom `path_converter` types, GraphQL endpoints, function-based views with manual method dispatch inside the body (only decorator-based `@api_view` or class-based views are guaranteed to work in v1).

---

### 1.3 Sandbox Runner — the core mechanism

```python
from django.db import transaction, connection
from django.test.utils import CaptureQueriesContext
from django.test import RequestFactory

def run_isolated(view_func, method, path, user=None, data=None):
    with transaction.atomic():
        sid = transaction.savepoint()
        try:
            factory = RequestFactory()
            request = getattr(factory, method.lower())(path, data=data, content_type="application/json")
            if user:
                request.user = user  # bypass auth middleware entirely

            with CaptureQueriesContext(connection) as ctx:
                response = view_func(request)

            return {
                "status_code": response.status_code,
                "queries": list(ctx.captured_queries),
                "query_count": len(ctx.captured_queries),
            }
        finally:
            transaction.savepoint_rollback(sid)
```

Key decisions, and why:

- **No separate database.** `transaction.atomic()` + `savepoint_rollback` on the user's actual dev DB. Zero migration/connection-string management for the user, zero teardown logic to maintain.
- **Auth bypass = attach `request.user` directly**, skip the auth middleware chain entirely. `RequestFactory` builds a bare `WSGIRequest` — middleware never runs unless invoked, so there's nothing to bypass, only something to add.
- **Known limitation surfaced in the UI, not silently ignored:** rollback undoes DB writes, not real side effects (outbound `requests.post`, `smtplib`, Celery `.delay()`, Channels `group_send`). V1 does not mock these. Grep the view's source (`inspect.getsource`) for a small denylist of import/call names and show a banner: *"This endpoint may trigger external side effects that won't be rolled back."*

**Punt to v2:** intercepting/mocking outbound calls (needs `responses`/`unittest.mock.patch` injected per-endpoint); Channels/websocket endpoint profiling (needs `TransactionTestCase`-style handling, different execution path entirely, not a `RequestFactory` call).

---

### 1.4 Mock Data Generator

Thin wrapper around **`model_bakery`** rather than dynamically composed `factory_boy` classes — `baker.make(Model, _quantity=N)` already does field-type inference + FK resolution with zero per-model config.

```python
from model_bakery import baker

def generate_mock_data(model, count, overrides=None):
    return baker.make(model, _quantity=count, **(overrides or {}))
```

**Sample-entry recovery flow — what happens when `baker.make()` fails validation:**

1. Catch `ValidationError` / `IntegrityError`. Extract the model name and failing field(s).
2. Prompt the user for **one complete, valid entry** for that model (not a per-field patch — one form submit).
3. For the field(s) that actually failed: **reuse the user's exact value verbatim across all N generated rows.** Don't attempt to infer the validator's pattern and generate variations — that's a mini regex-generation problem, and getting it wrong silently produces invalid data instead of failing loudly. Reusing the literal value is the honest version of "we can't guess your custom rule."
4. For every other field on the model, let `model_bakery` keep generating normally — the user only solves the field that actually broke.
5. **Uniqueness check before reuse:** if the failing field has `unique=True`, reusing one value N times will fail on row 2 with an `IntegrityError`. Detect this up front and fall back to generating exactly 1 row from the sample, with an explicit note: *"`tax_code` is unique and custom-validated — generated 1 record; add more manually if you need bulk data for this model."* Don't try to auto-suffix or mutate the value — that risks breaking whatever custom format the validator enforces.
6. **Cache the accepted sample** in an in-memory dict keyed by `model_name.field_name` for the life of the dev server process. Pre-fill it on subsequent runs instead of re-prompting — no new persistence layer, no migrations, consistent with v1's "no DB-backed history" scope.

**Punt to v2:** a plugin system for community-contributed field generators; smart `choices=` bias toward realistic-looking values (model_bakery already picks a valid choice, just not necessarily "realistic" — polish, not a blocker); `Polyfactory` as a swap-in generator once a second ORM adapter exists (Polyfactory already supports Django, SQLAlchemy, Pydantic, SQLModel — worth adopting when adapter #2 is real, not before).

---

### 1.5 Analyzer — query fingerprinting & N+1 detection

Regex-only fingerprinting breaks on `IN (...)` list-length variance, whitespace/casing, and alias naming — so v1 uses **`sqlglot`** (AST parse, not token/regex matching) instead:

```python
import sqlglot
import sqlglot.expressions as exp

def fingerprint(raw_sql: str) -> str:
    parsed = sqlglot.parse_one(raw_sql)

    # 1. Strip individual literals (numbers, quoted strings)
    for node in parsed.find_all(exp.Literal):
        node.replace(exp.Literal.string("?"))

    # 2. Collapse IN (...) lists to a single placeholder regardless of length
    #    (must replace the whole expression list, not just each literal inside it —
    #    test this explicitly, it's the part that's easy to get wrong)
    for node in parsed.find_all(exp.In):
        node.set("expressions", [exp.Literal.string("?")])

    # 3. Canonicalize Django's auto-generated table aliases to positional placeholders
    alias_map = {}
    for node in parsed.find_all(exp.TableAlias):
        alias_map.setdefault(node.this.name, f"T{len(alias_map)}")
        node.this.set("this", alias_map[node.this.name])

    return parsed.sql()
```

Plus one more normalization step done separately: **sort top-level `AND`-chained WHERE conditions alphabetically by column name** before comparing fingerprints (safe only when the top-level operator is a pure `AND` chain — skip this for anything involving `OR` or nested boolean logic, where reordering isn't semantically safe to do generically).

```python
def detect_n_plus_one(queries: list[dict], threshold: int = 3) -> list[dict]:
    from collections import defaultdict
    groups = defaultdict(list)
    for q in queries:
        groups[fingerprint(q["sql"])].append(q)

    flags = []
    for fp, group in groups.items():
        if len(group) >= threshold and fp.strip().upper().startswith("SELECT"):
            flags.append({
                "fingerprint": fp,
                "count": len(group),
                "suggestion": suggest_fix(fp, group),
            })
    return flags
```

`threshold = 3` as the default — two repeated queries is common and often fine; three-plus of the same shape is a much lower-noise signal for a junior dev's first impression of the tool.

`suggest_fix()` stays simple in v1: pattern-match the fingerprint's table name against the FK relationships already known from the Introspector step, and emit a templated string (`.select_related('author')` for FK/O2O, `.prefetch_related()` for reverse FK / M2M). String templating against known relationship metadata, not code analysis.

**On "100% accuracy" — worth being precise about the ceiling.** Fingerprinting can only normalize *syntactic* variation. It cannot solve general *semantic* equivalence — `SELECT * FROM a JOIN b ON a.id=b.a_id` vs. the same logic as a subquery are structurally different ASTs with identical results, and proving arbitrary SQL statements semantically equivalent is undecidable in the general case. That's not a gap in this implementation — it's true for any fingerprinting approach, for anyone. The four steps above (literal stripping, `IN` collapsing, alias canonicalization, safe `AND` reordering) get v1 to effectively 100% on the actual space of queries **Django's ORM generates for a repeated queryset pattern in a loop** — which is the real-world case being detected (N+1 in application code, not adversarial hand-written SQL). Frame the internal goal as "reliable for ORM-generated patterns," not "100% for all possible SQL" — the former is achievable, the latter isn't achievable by anyone.

**Still explicitly punted:**
- **Nested subqueries** — fingerprinting normalizes literals within them but doesn't restructure query shape; a real structural diff between equivalent join/subquery forms is a v2 problem if it turns out to matter in practice.
- **`OR`-involving WHERE clauses** — deliberately left unsorted since reordering isn't generically safe; revisit only if false negatives here turn out to be common.

---

### 1.6 Dashboard

Server-rendered HTML + Tailwind (via CDN, no build step) + a Django view returning the Analyzer's JSON. Single page: endpoint list on the left, click one → mock-data-count input + "Run" button → results panel showing query count, total time, and flagged N+1 groups highlighted in red. No SPA framework, no separate frontend build.

**Validation-error UI:** when the mock generator hits the sample-entry flow (§1.4), the dashboard shows a modal — model name, failing field, Django's own validation message, one input for the sample value, "Apply & Continue." Same visual language as the rest of the error/warning states (high contrast, actionable copy) per the original design philosophy.

**Punt to v2:** historical run tracking / trend charts (needs a persistence layer — deliberately excluded from v1 since it adds migrations to the user's project).

---

## 2. What "V1 done" looks like

`pip install`, add to `INSTALLED_APPS`, hit `/dqs/`, see your DRF endpoints listed, click one, generate N mock rows (handling validation failures via the one-sample-entry prompt), run it, see query count + red-flagged N+1 groups (fingerprinted via `sqlglot`, not regex) with a plain-English fix suggestion. Everything above this line ships. Everything under "punt to v2" doesn't — each punt has a one-line reason attached so nobody has to re-litigate the decision later.
