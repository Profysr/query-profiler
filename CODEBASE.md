# CODEBASE.md — DQS (da-profiler) Complete Context Reference

> **For agents and developers.** This file replaces `codebase.json` as the single source of truth for understanding this project. It is meant to be read at the start of any task.

---

## 1. Project Overview

| Field | Value |
|---|---|
| **Package name** | `dqs` |
| **PyPI name** | `da-profiler` |
| **Version** | `0.1.0` |
| **Python** | ≥ 3.10 |
| **License** | MIT |

**What this project does in plain English:**

Imagine you have a Django website with an API. Every time someone calls that API, Django might secretly run 50 database queries behind the scenes — most of them unnecessary duplicates. That slowness is called the **N+1 problem**.

DQS is a **development-only profiling tool** that:
1. Calls your API endpoints automatically inside a **safe sandbox** (all database changes are thrown away after each test — like a practice run that never saves).
2. **Records every SQL query** that ran during that call, including which file and line number triggered it.
3. **Detects N+1 patterns** by fingerprinting repeated queries and counting them.
4. **Suggests fixes** like `.select_related()` or `.prefetch_related()`.
5. **Scans your source code** (without running it) to warn about risky patterns like DB queries inside loops.

---

## 2. Absolute Rules (Agents Must Follow)

> These rules must never be broken. If a change would break one, stop and reconsider.

| # | Rule |
|---|---|
| 1 | `dqs/core/` must be **pure Python**. No Django, DRF, or database imports allowed there. |
| 2 | All DB profiling **must run inside `transaction.atomic()` + savepoint + rollback**. Changes must never persist. |
| 3 | Static AST scanning must **never import or execute** the code it is analyzing. |
| 4 | The execution pipeline has four ordered steps: `resolve_path_step` → `probe_route_step` → `seed_resource_step` → `profile_target_step`. |
| 5 | When you modify **any function or class signature**, check and update **all call sites** in `dqs/` and `tests/`. |
| 6 | DQS must **refuse to run** when `DEBUG=False`. It is a dev-only tool and must never touch production databases. |

---

## 3. File Structure

```
django-profiler/
├── dqs/                          ← Main Python package
│   ├── __init__.py
│   ├── core/                     ← Framework-agnostic analysis engine (no Django imports)
│   │   ├── analyzer.py           ← SQL fingerprinting + N+1 detection
│   │   ├── static_advisor.py     ← AST code scanner (reads code, never runs it)
│   │   └── targets.py            ← Target dataclass (what can be profiled)
│   └── adapters/
│       └── drf/                  ← Django REST Framework integration layer
│           ├── apps.py           ← Django AppConfig (startup safety check)
│           ├── discovery.py      ← Finds all routes, signals, tasks in the project
│           ├── introspector.py   ← Reads URL tree; extracts route metadata
│           ├── body_inferrer.py  ← Request body payload inferrer for DRF serializers / forms
│           ├── converters.py     ← Resolves URL path parameters to real values
│           ├── mock_generator.py ← Model mock data generator with validation recovery & uniqueness guards
│           ├── query_interceptor.py ← Hooks into Django DB driver to capture queries
│           ├── runner.py         ← Executes sandboxed requests; orchestrates everything
│           └── schema_advisor.py ← Checks DB schema for missing indexes / PK strategy
│
├── tests/
│   ├── conftest.py               ← Shared pytest fixtures
│   ├── core/
│   │   ├── conftest.py
│   │   ├── test_analyzer.py      ← Tests for fingerprint() and detect_n_plus_one()
│   │   └── test_static_advisor.py ← Tests for StaticASTAdvisor
│   └── adapters/
│       └── drf/
│           ├── conftest.py       ← DRF-specific fixtures (fake Django app, models, views)
│           ├── test_body_inferrer.py
│           ├── test_converters.py
│           ├── test_discovery.py
│           ├── test_introspector.py
│           ├── test_query_interceptor.py
│           ├── test_runner.py
│           └── test_runner_integration.py
│
├── demos/drf/                    ← Demo Django project used by tests
├── pyproject.toml                ← Build config, dependencies, pytest config
├── CODEBASE.md                   ← This file (replaces codebase.json)
├── ARCHITECTURE.md               ← High-level architecture diagram
├── ROADMAP.md                    ← Future feature plans
└── CHANGELOG.md                  ← Version history
```

---

## 4. Architecture Layers

```
┌─────────────────────────────────────────────────────────────┐
│  MCP / UI / CLI  (calls DjangoSandboxRunner methods)         │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│  dqs/adapters/drf/   (Django integration layer)              │
│  ┌──────────────┐  ┌────────────┐  ┌──────────────────────┐ │
│  │ introspector │  │ converters │  │ discovery            │ │
│  │ (reads URLs) │  │ (resolves  │  │ (finds all targets:  │ │
│  │              │  │  params)   │  │  views/tasks/signals)│ │
│  └──────┬───────┘  └─────┬──────┘  └──────────────────────┘ │
│         └────────────────▼                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  runner.py  (DjangoSandboxRunner)                     │   │
│  │  - profile_callable()  ← atomic savepoint wrapper     │   │
│  │  - execute_isolated()  ← full HTTP sandbox pipeline   │   │
│  │  - trigger_signal_target() / trigger_task_target()    │   │
│  │  - _build_execution_result() ← shared result builder  │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                         │                                    │
│  ┌──────────────────────▼───────────────────────────────┐   │
│  │  query_interceptor.py  (hooks into Django DB driver)  │   │
│  └──────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│  dqs/core/   (pure Python, no Django, no DB)                 │
│  ┌───────────────────┐  ┌────────────────┐  ┌────────────┐  │
│  │ analyzer.py       │  │ static_advisor │  │ targets.py │  │
│  │ fingerprint()     │  │ StaticAST      │  │ Target     │  │
│  │ detect_n_plus_one │  │ Advisor        │  │ TargetKind │  │
│  └───────────────────┘  └────────────────┘  └────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. File-by-File Reference

---

### `dqs/core/targets.py`

**Purpose:** Defines the `Target` dataclass — the universal data container for anything DQS can profile (a URL route, a signal handler, a Celery task, or a WebSocket consumer).

Think of it like a **job card** in a factory. Every profiling job gets a card that says: "what is this thing, can it be triggered, and how?"

#### `TargetKind` (type alias)
```python
TargetKind = Literal["view", "signal", "task", "consumer", "static_only"]
```
Labels what category the target is. Used by the runner to decide how to trigger it.

#### `Target` (dataclass)
| Field | Type | Meaning |
|---|---|---|
| `id` | `str` | Unique identifier, e.g. `"view:/api/books/"` |
| `kind` | `TargetKind` | `"view"`, `"signal"`, `"task"`, etc. |
| `triggerable` | `bool` | Can DQS actually run this target? |
| `trigger_spec` | `dict` | How to trigger it (path, method, task name, signal name) |
| `static_findings` | `list` | Pre-run static analysis warnings (e.g. ORM call in loop) |

---

### `dqs/core/analyzer.py`

**Purpose:** Pure Python SQL analysis engine. Fingerprints SQL queries and detects the N+1 pattern. Has zero Django dependencies.

#### `fingerprint(raw_sql: str) -> str`

**What it does:** Takes a raw SQL string and produces a normalized "template" of that query, stripping out all specific values. Two queries that do the same logical thing but with different IDs will produce the same fingerprint.

**Why:** If you run `SELECT ... WHERE id = 1`, then `WHERE id = 2`, then `WHERE id = 3` — those look different but are the same pattern. Fingerprinting lets us detect that.

**Simple example:**
```
Input:  SELECT "book"."title" FROM "book" WHERE "book"."id" = 42
Output: SELECT T0.title FROM book AS T0 WHERE T0.id = '?'

Input:  SELECT "book"."title" FROM "book" WHERE "book"."id" = 99
Output: SELECT T0.title FROM book AS T0 WHERE T0.id = '?'   ← same fingerprint!
```

**Steps it does internally:**
1. Parse SQL into an AST using `sqlglot`
2. Replace all literal values (`42`, `"Alice"`) with `?`
3. Collapse `IN (1, 2, 3)` → `IN ('?')`
4. Rename all table aliases to `T0`, `T1`, `T2` (stable order)
5. Sort `WHERE a AND b` conditions alphabetically (so `WHERE b AND a` gives the same result)

#### `_contains_or(condition)` *(private helper)*
Returns `True` if a WHERE clause contains an `OR`. Used to skip step 5 above for OR conditions, since sorting parts of an OR clause would change its meaning.

#### `_sorted_and_chain(condition)` *(private helper)*
Flattens a chain of `AND` conditions, sorts them by their SQL text, and rebuilds the chain. This ensures `WHERE a=1 AND b=2` and `WHERE b=2 AND a=1` produce the same fingerprint.

#### `suggest_fix(fp, relationships, src_loc) -> str`

**What it does:** Generates a human-readable suggestion for fixing an N+1 problem.

**Simple example:**
```
Input:  fingerprint of a query on table "author", relationship type "select_related"
Output: "Potential N+1 detected on table 'author' at `views.py:42`.
         Fix by appending .select_related('author') to your base queryset."
```

It first tries to use `relationships` metadata (which tells it the field name and FK type), then falls back to a generic suggestion if metadata isn't available.

#### `detect_n_plus_one(queries, threshold=3, relationships) -> List[Dict]`

**What it does:** Takes a list of captured SQL queries (each with a `"sql"` key), groups them by fingerprint, and returns all fingerprints that appear `threshold` or more times as SELECT statements.

**Simple example:**
```
If your endpoint runs:
  SELECT author WHERE id=1   → fingerprint A
  SELECT author WHERE id=2   → fingerprint A
  SELECT author WHERE id=3   → fingerprint A
  SELECT books                → fingerprint B

Result: fingerprint A is flagged (count=3, threshold=3).
        fingerprint B is not flagged (count=1).
```

Returns a list of dicts with: `fingerprint`, `count`, `src_loc`, `suggestion`, `sample_queries`.

---

### `dqs/core/static_advisor.py`

**Purpose:** Scans Python source code using Python's built-in `ast` module to find dangerous patterns — **without importing or running the code**. Like a teacher reading your homework before you submit it, catching mistakes without actually executing the program.

#### `StaticASTAdvisor` (class)

The main scanner. You give it source code as a string; it parses it into an AST tree and walks through every node looking for problems.

**Constructor:**
```python
advisor = StaticASTAdvisor(source_code="...", filename="views.py")
```

**`run() -> List[Dict]`**
Parses and visits the entire AST. Returns a list of findings. Each finding is a dict with `type`, `message`, `line`, and `severity`.

**`visit_Import` / `visit_ImportFrom`** *(AST visitor hooks)*
Builds an `import_map` — a dictionary that resolves aliases back to their real names.
- Example: `import requests as r` → `{"r": "requests"}`
- Needed so when the scanner sees `r.get(...)`, it knows that's really `requests.get(...)`.

**`visit_For` / `visit_AsyncFor` / `visit_While`** *(AST visitor hooks)*
Increments and decrements a `_loop_depth` counter as the scanner enters/exits loops. Any call detected while `_loop_depth > 0` is inside a loop.

**`visit_Call`** *(AST visitor hook — the main logic)*
Called for every function call in the code. Does three checks:

1. **ORM call inside a loop?** → Emits `ORM_CALL_IN_LOOP` finding.
2. **Blocking I/O call?** → Emits `BLOCKING_EXTERNAL_CALL` finding (e.g. `requests.get`, `time.sleep`).
3. **Filter/exclude/order_by call?** → Collects field names into `queried_fields` (used by `schema_advisor.py`).

**`_is_orm_call(node, call_repr) -> (bool, confidence)`**
Determines if a call is likely a Django ORM call.
- `"high"` confidence: explicitly uses `.objects.` (e.g. `Book.objects.filter(...)`)
- `"low"` confidence: method name is in the ORM set (`.get()`, `.filter()`) but the receiver isn't obviously a queryset. Could be a false positive.

**`_is_blocking_call(call_repr) -> bool`**
Checks if the call starts with a known blocking I/O prefix like `requests.get`, `smtplib.SMTP`, `time.sleep`.

**`_get_call_name(node) -> str`**
Extracts the full dotted name from a Call AST node. `requests.get(url)` → `"requests.get"`.

**`_resolve_alias(name) -> str`**
Resolves a local alias using `import_map`. `r.get` → `requests.get` if `r` was imported as `requests`.

**Module-level constants:**
- `DJANGO_ORM_METHODS` — set of ORM method names like `filter`, `get`, `create`, etc.
- `BLOCKING_CALL_PREFIXES` — set of blocking call prefixes like `requests.get`, `time.sleep`.

---

### `dqs/adapters/drf/apps.py`

**Purpose:** Django `AppConfig` — the entry point Django uses when loading the `dqs.adapters.drf` app.

#### `DQSConfig` (class, extends `AppConfig`)
- Sets app name, label, and verbose name.
- **`ready()`**: Called by Django on startup. **Hard-stops the server** if `DEBUG=False`, refusing to load in production. This is a critical safety gate.

---

### `dqs/adapters/drf/introspector.py`

**Purpose:** Reads the entire Django URL configuration tree and extracts structured metadata about every DRF endpoint — what path it serves, what HTTP methods it supports, what model it talks to, and what URL parameters it requires.

Think of it like a **city map reader** — it reads the entire map of your website (URL patterns) and returns a list of every place on the map with directions on how to get there.

#### `PathParam` (dataclass)
| Field | Type | Meaning |
|---|---|---|
| `name` | `str` | Parameter name, e.g. `"pk"` |
| `converter` | `str` | Type, e.g. `"int"`, `"slug"`, `"uuid"` |

#### `RouteMetadata` (dataclass)
The full description of one URL endpoint.

| Field | Meaning |
|---|---|
| `path` | URL path, e.g. `"/api/books/<int:pk>/"` |
| `methods` | HTTP methods allowed, e.g. `["GET", "PUT"]` |
| `view_name` | Django URL name, e.g. `"book-detail"` |
| `view_type` | `"DRF_ViewSet"` or `"DRF_APIView"` |
| `executable` | `True` if DQS can trigger it |
| `path_params` | List of `PathParam` objects |
| `target_model` | e.g. `"library.Book"` |
| `reason_unexecutable` | Why it can't be triggered, if applicable |
| `view_callable` | The actual view class, for static analysis |
| `has_path_params` | `True` if path has any parameters |

#### `DjangoIntrospector` (class)

**Constructor:** Checks `DEBUG=True`, gets Django's root URL resolver.

**`list_all_routes() -> List[RouteMetadata]`**
Entry point. Starts crawling the URL tree from the root and returns all discovered routes.

**`_extract_patterns(patterns, prefix, routes)`** *(private)*
Recursively walks the URL tree. Two types of nodes:
- `URLResolver` → a group of URLs (like `include('api.urls')`). Recurse into it.
- `URLPattern` → a single endpoint. Analyze it.

Skips paths starting with `/dqs/` to avoid infinite loops on its own dashboard routes.

**`_analyze_view(pattern, full_path) -> Optional[RouteMetadata]`** *(private)*
Inspects one URL endpoint:
1. Gets the view class (handling DRF `as_view()` wrappers).
2. Skips non-DRF views (plain Django views are ignored).
3. Determines HTTP methods from ViewSet actions or `http_method_names`.
4. Calls `_extract_model_from_class()` and `_extract_path_params()`.

**`_extract_path_params(pattern) -> List[PathParam]`** *(private)*
Delegates to `PathConverterResolver.extract_converters_from_pattern()`.

**`extract_view_lookup_map(view_class) -> Dict[str, str]`**
Reads DRF's `lookup_url_kwarg` and `lookup_field` from the view class.
- Example: a view with `lookup_url_kwarg = "article_slug"` and `lookup_field = "slug"` → `{"article_slug": "slug"}`
- Needed so the parameter resolver knows that `article_slug` in the URL maps to the `slug` field on the model.

**`_extract_model_from_class(view_class) -> Optional[str]`** *(private)*
Four-step model discovery cascade (tries each in order, stops at first success):
1. Read `queryset.model` attribute.
2. Read `model` attribute directly.
3. Read `serializer_class.Meta.model`.
4. Instantiate the view with a dummy request and call `get_queryset()` to see what model it returns.

---

### `dqs/adapters/drf/converters.py`

**Purpose:** When a URL has path parameters like `/books/<int:pk>/`, this module figures out a real value to put there. It's the **parameter solver** of the pipeline.

Think of it like a GPS that needs to know your exact house number to give directions. If you don't provide it, it either finds a house that already exists in the database, or makes up a reasonable-looking number.

#### `PathConverterResolver` (class — all `@classmethod`)

**`resolve_converter_type(converter_name) -> str`**
Normalizes a Django converter class name string to a simple type.
- `"IntConverter"` → `"int"`, `"SlugConverter"` → `"slug"`, empty → `"str"`

**`extract_converters_from_pattern(pattern) -> List[PathParam]`**
Reads `RoutePattern.converters` (the dict Django builds from `<int:pk>` in a path string) and returns a list of `PathParam` objects.

**`generate_synthetic_fallback(param_name, converter_type) -> Any`**
When no database record exists to get a real value from, returns a deterministic fake value:
| Converter type | Returns |
|---|---|
| `int` | `1` |
| `uuid` | `"123e4567-e89b-12d3-a456-426614174000"` |
| `slug` | `"test-slug"` |
| `str` / `path` | `"test-param"` (or `"test-slug"` if param name contains `"slug"`) |

**`extract_from_model_instance(instance, param_name, lookup_map) -> Any`**
Given a real model instance (e.g. a `Book` object), extracts the value for a named path parameter. Uses `lookup_map` to translate URL kwarg names to model field names. Falls back through `pk`, `id`, `slug`, `code` if the named field isn't found.

**`resolve_params_for_route(route, explicit_params, auto_generate_if_missing, lookup_map)`**
The core resolution pipeline:
1. Start with any explicitly provided params.
2. If params are still missing and the route has a `target_model`, look for an existing DB record (`model_class.objects.first()`), or create one with `baker.make()`.
3. Extract param values from the found/created instance.
4. For any param still missing: use `generate_synthetic_fallback()`.

Returns `(resolved_params_dict, created_instance_or_None)`.

**`render_concrete_url(route, resolved_params) -> str`**
Turns a route + resolved params into a real URL string:
1. Try `reverse(route.view_name, kwargs=resolved_params)`.
2. Fallback: substitute `<int:pk>` style placeholders with regex substitution.

**`build_executable_url(route, explicit_params, auto_generate_if_missing, lookup_map)`**
The top-level public entry point. Calls `resolve_params_for_route()` then `render_concrete_url()`.
Returns `(concrete_url, params, created_instance)`.

---

### `dqs/adapters/drf/body_inferrer.py`

**Purpose:** Inspects DRF view classes, `serializer_class` definitions, or Django `form_class` definitions to infer and generate realistic mock request body payload dictionaries for `POST`, `PUT`, and `PATCH` endpoints when `data=None` is passed.

#### `infer_request_body(view_func_or_cls) -> Optional[Dict[str, Any]]`
Main entry point. Inspects a view callable or view class, extracts its serializer or form class, and returns an inferred mock payload dictionary.

#### `infer_body_from_serializer(serializer_cls) -> Dict[str, Any]`
Instantiates a DRF serializer class and inspects non-read-only fields to construct a mock JSON payload matching expected data types (`CharField`, `EmailField`, `SlugField`, `IntegerField`, `DateTimeField`, `ChoiceField`, `PrimaryKeyRelatedField`, `NestedSerializer`, etc.).

#### `infer_body_from_form(form_cls) -> Dict[str, Any]`
Instantiates a Django Form class and inspects active fields to generate a mock payload dictionary.

---

### `dqs/adapters/drf/query_interceptor.py`

**Purpose:** A Python context manager that hooks into Django's database connection and secretly listens to every SQL query that runs while it's active. Like a security camera at the database door.

#### `QueryInterceptor` (class, context manager)

**`__enter__`**
Calls `connection.execute_wrapper(self._wrapper)` — Django's official API for wrapping every SQL execution. From this point on, every DB query goes through `_wrapper()`.

**`__exit__`**
Removes the wrapper, restoring normal DB behavior.

**`_wrapper(execute, sql, params, many, context)`**
Called for every SQL query. It:
1. Records the start time with `time.perf_counter()` (high precision).
2. Runs the actual query via `execute(sql, params, many, context)`.
3. Calculates duration in milliseconds.
4. Calls `_extract_source_location()` to find which app file triggered this query.
5. Appends `{"sql": sql, "time_ms": duration, "src_loc": source_loc}` to `captured_queries`.

**`_extract_source_location() -> Optional[str]`**
Walks the live Python call stack (`inspect.stack()`). Skips all frames from Django internals, DRF, and DQS itself. Returns the first frame that belongs to user code, formatted as `"views.py:42"`.

**Example output of `captured_queries`:**
```python
[
    {"sql": "SELECT ...", "time_ms": 1.2, "src_loc": "api/views.py:28"},
    {"sql": "SELECT ...", "time_ms": 0.9, "src_loc": "api/serializers.py:15"},
]
```

---

### `dqs/adapters/drf/schema_advisor.py`

**Purpose:** Reads Django model metadata (without touching the database) to give static schema-level advice. Checks if models have proper primary key strategies and if frequently queried fields are indexed.

#### `check_pk_strategy(model_path) -> List[Dict]`

Loads the model class and checks the type of its primary key field. If it's an auto-increment integer (`AutoField`, `BigAutoField`, `SmallAutoField`), it returns a `PK_STRATEGY_ADVICE` warning suggesting UUIDv7 for write-heavy or distributed apps. Returns empty list otherwise.

#### `check_missing_indexes(model_path, queried_fields) -> List[Dict]`

Given a model and a list of field names that are used in `.filter()/.exclude()/.order_by()` calls (collected by `StaticASTAdvisor`), it:
1. Builds a set of indexed field names from the model's `db_index=True`/`unique=True` fields and `Meta.indexes`.
2. Always adds the primary key name (always indexed).
3. For each queried field not in the indexed set → emits a `MISSING_INDEX` finding.

Strips `order_by` prefixes like `-` and lookup suffixes like `__gte` before comparing.

---

### `dqs/adapters/drf/discovery.py`

**Purpose:** The **scanner** that finds everything in your Django project that DQS can profile. It combines results from introspection (URLs), Celery (tasks), and Django Channels (WebSocket consumers) into a unified list of `Target` objects.

#### `DjangoTargetDiscovery` (class)

**Constructor:** Accepts a pre-built list of `RouteMetadata` objects from `DjangoIntrospector`.

**`discover_all() -> List[Target]`**
The main method. Runs three discovery passes and returns a flat list of `Target` objects:

1. **URL Views** — Iterates `introspector_routes`. For each route:
   - Runs `check_pk_strategy()` and `check_missing_indexes()` (static schema checks).
   - Tries to get source code of the view callable and run `StaticASTAdvisor` to collect `queried_fields` for the index check.
   - Creates a `Target(kind="view", ...)`.

2. **Celery Tasks** — Tries to import `celery.current_app`. For each registered task not starting with `"celery."`:
   - Runs `_analyze_callable_statically()` on the task function.
   - Creates a `Target(kind="task", ...)`.

3. **Django Channels Consumers** — Reads `settings.ASGI_APPLICATION`, walks the websocket routing to find consumer classes.
   - Sets `triggerable=False` (execution is a v2.0+ feature).
   - Creates `Target(kind="consumer", ...)`.

> **Note:** Signal discovery is written but commented out (pending v2.0 work).

**`_analyze_callable_statically(func) -> List[Dict]`** *(private)*
Gets source code of a callable with `inspect.getsource()`, runs `StaticASTAdvisor` on it, returns the findings. Returns `[]` on any failure (safe to call on anything).

**`_resolve_sender_model(sender_id) -> Optional[str]`** *(private)*
Django stores signal senders by `id(SenderClass)` (memory address), not the class itself. This method reverse-looks that up by scanning `apps.get_models()` to find which model class has that memory id. Returns `"app_label.ModelName"` or `None`.

**`_discover_consumers() -> List[Target]`** *(private)*
Reads `settings.ASGI_APPLICATION`, imports the ASGI app, and walks its `application_mapping["websocket"].routes` to find consumer classes.

---

### `dqs/adapters/drf/runner.py`

**Purpose:** The **engine room** of DQS. Brings together all other modules to execute sandboxed HTTP requests, capture queries, run N+1 analysis, and return structured results. Also handles signal and task triggering.

#### `ExecutionResult` (dataclass)

The return type of all trigger methods. Always returned, even on error.

| Field | Type | Meaning |
|---|---|---|
| `route` | `str` | URL or target ID that was profiled |
| `status_code` | `int` | HTTP status (or 500 for errors) |
| `metrics` | `dict` | `total_time_ms`, `db_time_ms`, `total_queries`, `unique_fingerprints`, `n_plus_one_detected` |
| `queries` | `list` | All captured SQL queries with fingerprint, time, source location |
| `analysis` | `list` | N+1 findings from `detect_n_plus_one()` |
| `error` | `str or None` | Error message if something went wrong |
| `side_effect_warnings` | `list` | Static scan warnings (e.g. `requests.get` found in view) |
| `response_body` | `any` | Parsed response data (DRF `.data` or JSON) |
| `seeded_records` | `list` | Records created by `baker.make()` for this run |

**Example full output:**
```json
{
  "route": "/api/books/",
  "status_code": 200,
  "metrics": {
    "total_time_ms": 14.25,
    "db_time_ms": 4.12,
    "total_queries": 4,
    "unique_fingerprints": 2,
    "n_plus_one_detected": true
  },
  "queries": [
    {"sql": "SELECT ...", "fingerprint": "SELECT T0.id ...", "time_ms": 1.2, "source_location": "api/views.py:28"}
  ],
  "analysis": [
    {
      "fingerprint": "SELECT T0.id, T0.name FROM author AS T0 WHERE T0.id = '?'",
      "count": 3,
      "source_location": "api/serializers.py:15",
      "suggestion": "Fix by appending .select_related('author')..."
    }
  ]
}
```

#### `DjangoSandboxRunner` (class)

**Constructor:** Verifies `DEBUG=True`. Creates a `rest_framework.test.APIRequestFactory`.

---

#### `profile_callable(func, *args, setup=None, **kwargs)`

**The core atomic sandbox wrapper.** Executes any callable inside:
- `transaction.atomic()` — wraps everything in one DB transaction
- `transaction.savepoint()` — creates an inner restore point
- `QueryInterceptor()` — captures all SQL queries
- `transaction.savepoint_rollback(sid)` — always reverts everything, even on success

The `setup` parameter runs **inside the transaction but outside the interceptor**. This is where seeding (`baker.make`) goes — seeded rows are rolled back too, but their INSERT queries don't pollute the captured query list.

Returns `(result, captured_queries, db_duration_ms, setup_result)`.

**Simple analogy:** Like a flight simulator — you fly the plane (run the view), everything feels real (real DB operations), but when you're done, nothing actually happened (rollback). The black box (query interceptor) recorded everything.

---

#### Step-Driven Pipeline Methods (MCP Entries)

These four methods let an agent (or MCP layer) run the execution pipeline step by step, observing each stage.

**`resolve_path_step(route_meta, explicit_params, lookup_map) -> Dict`**
Step 1: Calls `PathConverterResolver.build_executable_url()` and returns the resolved URL and params.

**`probe_route_step(concrete_url, method, user) -> Dict`**
Step 2: Issues an un-intercepted request to verify the route responds. Returns `{status_code, exists, error}`.

**`seed_resource_step(target_model, seed_count) -> Dict`**
Step 3: Creates `seed_count` mock records using `baker.make()`. Returns info about created instances. **Note:** This step does NOT roll back — it's meant for pre-seeding before the profiled run.

**`profile_target_step(...) -> ExecutionResult`**
Step 4: Delegates to `execute_isolated()`. The final full execution step.

---

#### `execute_isolated(url_name_or_path, method, path_params, query_params, data, user, relationships, seed_count, target_model, content_type) -> ExecutionResult`

The full HTTP sandbox pipeline. Call this to run one complete profiled request.

**Flow:**
1. Validates HTTP method.
2. Builds a `RouteMetadata` and calls `PathConverterResolver.build_executable_url()` to resolve the concrete URL.
3. Calls `resolve(resolved_path)` to get Django's `ResolverMatch`.
4. Runs `_detect_side_effects()` on the view function via static AST scan.
5. Opens `profile_callable()` with:
   - `_seed()` as the `setup` function (creates `seed_count` records via `baker.make()`).
   - `_sandbox_execution()` as the main callable (constructs DRF request, sets user, calls view).
6. Calls `_build_execution_result()` to format and analyze the captured data.

---

#### `trigger_signal_target(target: Target) -> ExecutionResult`

Triggers a Django signal (post_save, pre_save, post_delete, pre_delete) by using `baker.make()` to create or delete a model instance, which fires the signal naturally. Wraps everything in `profile_callable()`. Returns `_build_execution_result()`.

#### `trigger_task_target(target: Target, *task_args, **task_kwargs) -> ExecutionResult`

Imports the named Celery task from `current_app.tasks`, calls `task_func.run()` directly (synchronously, no broker needed), wrapped in `profile_callable()`. Returns `_build_execution_result()`.

---

#### `_build_execution_result(route, status_code, queries_captured, db_duration, total_duration, response_body, seeded_records_info, side_effect_warnings, relationships) -> ExecutionResult`

**The shared result builder** — used by `execute_isolated`, `trigger_signal_target`, and `trigger_task_target`. Avoids code duplication.

Steps:
1. Formats raw `queries_captured` into the final list (adds `fingerprint` and `source_location` fields).
2. Calls `detect_n_plus_one()` to find N+1 groups.
3. Formats `analysis_payload` from the N+1 groups.
4. Builds the `metrics` dict.
5. Returns an `ExecutionResult`.

#### `_detect_side_effects(view_func) -> List[str]`

Gets the source code of the view function with `inspect.getsource()`, runs `StaticASTAdvisor`, and returns only `BLOCKING_EXTERNAL_CALL` warning messages. Silently returns `[]` on any failure.

#### `_parse_response_body(response) -> Optional[Any]`

Extracts a serializable response body from a DRF `Response` or raw `HttpResponse`. Tries `.data` first (DRF), then JSON-decodes `.content`.

---

## 6. Data Flow: Full End-to-End Example

```
User/Agent calls:
  runner.execute_isolated("/api/books/", method="GET", seed_count=5)

  1. PathConverterResolver.build_executable_url()
     → "/api/books/" (no params needed for list endpoint)

  2. django.urls.resolve("/api/books/")
     → ResolverMatch(func=BookListView.as_view(), ...)

  3. StaticASTAdvisor(BookListView source).run()
     → [] (no side effects found)

  4. profile_callable(_sandbox_execution, setup=_seed):
     ├── transaction.atomic()
     │   ├── savepoint(sid)
     │   ├── _seed() → baker.make(Book, _quantity=5) → 5 Book rows
     │   ├── QueryInterceptor().__enter__()  ← DB wire tap on
     │   │   ├── APIRequestFactory.get("/api/books/")
     │   │   ├── BookListView(request)
     │   │   │   ├── Book.objects.all()       → SQL captured (time=0.8ms, src=views.py:12)
     │   │   │   ├── Author.objects.get(id=1) → SQL captured (time=0.3ms, src=serializers.py:8)
     │   │   │   ├── Author.objects.get(id=2) → SQL captured (time=0.3ms, src=serializers.py:8)
     │   │   │   ├── Author.objects.get(id=3) → SQL captured (time=0.3ms, src=serializers.py:8)
     │   │   │   ├── Author.objects.get(id=4) → SQL captured (time=0.3ms, src=serializers.py:8)
     │   │   │   └── Author.objects.get(id=5) → SQL captured (time=0.3ms, src=serializers.py:8)
     │   ├── QueryInterceptor().__exit__()   ← DB wire tap off
     │   └── savepoint_rollback(sid)         ← ALL 5 books deleted from DB

  5. _build_execution_result():
     ├── fingerprint("SELECT ... WHERE author.id = 1") → "SELECT T0... WHERE T0.id = '?'"
     ├── fingerprint("SELECT ... WHERE author.id = 2") → "SELECT T0... WHERE T0.id = '?'"  ← same!
     ├── detect_n_plus_one() → 5 identical fingerprints → N+1 FLAGGED
     └── suggest_fix() → "Use .select_related('author')..."

  Returns ExecutionResult(
    status_code=200, metrics={n_plus_one_detected: True, total_queries: 6},
    analysis=[{fingerprint: ..., count: 5, suggestion: "...select_related..."}]
  )
```

---

## 7. Testing

### Running Tests

```bash
# Run only pure Python core tests (fast, no DB)
pytest -m core

# Run only Django/DRF adapter tests (needs DB)
pytest -m django

# Run everything
pytest
```

### Test Directory Map

| File | What it tests |
|---|---|
| `tests/core/test_analyzer.py` | `fingerprint()`, `detect_n_plus_one()`, `suggest_fix()` |
| `tests/core/test_static_advisor.py` | `StaticASTAdvisor` — loop detection, blocking calls |
| `tests/adapters/drf/test_converters.py` | `PathConverterResolver` pipeline |
| `tests/adapters/drf/test_introspector.py` | `DjangoIntrospector` — URL crawling, model extraction |
| `tests/adapters/drf/test_query_interceptor.py` | SQL capture, timing, source location |
| `tests/adapters/drf/test_runner.py` | `DjangoSandboxRunner` — sandbox, rollback, result building |
| `tests/adapters/drf/test_runner_integration.py` | Full end-to-end request → result integration test |
| `tests/adapters/drf/test_discovery.py` | `DjangoTargetDiscovery` — target enumeration |

### Test Infrastructure (`tests/adapters/drf/conftest.py`)
Creates a minimal in-memory Django project with a fake `Book` model and two views (`BookListView`, `BookDetailView`) for testing. All test DB operations use SQLite.

---

## 8. Key Dependencies

| Package | Why |
|---|---|
| `sqlglot` | SQL AST parser used by `analyzer.py` for fingerprinting |
| `django` | Web framework being profiled |
| `djangorestframework` | The DRF API layer being introspected and executed |
| `model_bakery` | Creates mock model instances for seeding |
| `psycopg2-binary` | PostgreSQL driver (optional, SQLite works for tests) |
| `pytest-django` | Django integration for pytest |

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **N+1 Problem** | When fetching N objects triggers N additional queries (e.g. loading 100 books causes 100 separate author lookups) |
| **Fingerprint** | A normalized SQL template with values replaced by `?`, so structurally identical queries can be grouped |
| **Savepoint** | A database bookmark inside a transaction. Rolling back to it undoes all changes since it was created |
| **Sandbox** | A safe environment where code runs as if real, but all database changes are thrown away after |
| **AST** | Abstract Syntax Tree — a structured representation of code that allows analysis without running the code |
| **Target** | Any code entry point DQS can profile: a URL route, signal handler, Celery task, or WebSocket consumer |
| **MCP** | Model Context Protocol — the agent interface that calls DQS pipeline steps |
| **`baker.make()`** | Creates a model instance with auto-generated realistic data. Like a factory that builds fake database rows |
| **`select_related`** | Django ORM optimization for ForeignKey/OneToOne — fetches related objects in a single JOIN query |
| **`prefetch_related`** | Django ORM optimization for ManyToMany/Reverse FK — fetches related objects in a separate batch query |
