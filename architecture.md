# Da Profiler — Architecture & System Design 🏗️

> **Da Profiler** (package `dqs`) is an isolated query profiling engine and static code advisor for Django applications. It automatically discovers endpoints, executes them safely inside self-rolling-back database savepoints, intercepts queries at the DB-driver boundary, normalizes SQL queries using AST fingerprinting to detect N+1 bottlenecks, and performs static code analysis on user code.

---

## 1. Core Architectural Principles

Da Profiler is built around three fundamental design principles:

1. **Framework-Agnostic Core (`dqs/core/`)**:
   - The core engine contains **zero Django or framework-specific imports**.
   - Handles SQL AST fingerprinting (`sqlglot`), N+1 aggregation algorithms, target abstractions (`Target`), and framework-independent static AST code scanning (`StaticASTAdvisor`).

2. **Framework Adapters (`dqs/adapters/`)**:
   - Framework-specific integration logic lives strictly inside adapters (e.g. `dqs/adapters/drf/`).
   - Adapters handle route discovery, ORM query interception, dynamic parameter resolution, synthetic mock data generation, body inference, and safe isolated execution.

3. **Zero Database Risk (Isolated Savepoints)**:
   - Profiled endpoints run strictly within `transaction.atomic()` savepoints.
   - All state changes (create, update, delete) are automatically rolled back when profiling finishes. The real database is never modified.

---

## 2. System Component Overview

```
                       +---------------------------------------+
                       |         Developer / AI Agent          |
                       +-------------------+-------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                            Da Profiler Core (dqs/core/)                           |
|                                                                                   |
|  +---------------------+   +--------------------------+   +--------------------+  |
|  |     Target Model    |   |     Static AST Advisor   |   |   AST Analyzer     |  |
|  |     (targets.py)    |   |   (static_advisor.py)    |   |   (analyzer.py)    |  |
|  +----------+----------+   +------------+-------------+   +---------+----------+  |
+-------------|---------------------------|---------------------------|-------------+
              |                           |                           |
              v                           v                           v
+-----------------------------------------------------------------------------------+
|                          Django Adapter (dqs/adapters/drf/)                       |
|                                                                                   |
|  +--------------------+    +---------------------------+    +------------------+  |
|  |  Target Discovery  |    |    DB Query Interceptor   |    | Sandbox Runner   |  |
|  |   (discovery.py)   |    |   (query_interceptor.py)  |    |   (runner.py)    |  |
|  +---------+----------+    +-------------+-------------+    +--------+---------+  |
|            |                             |                           |            |
|            v                             v                           v            |
|  +--------------------+    +---------------------------+    +------------------+  |
|  | Route Introspect   |    |  Dynamic Path Converters  |    |  Mock Generator  |  |
|  | (introspector.py)  |    |      (converters.py)      |    |(mock_generator.py)|
|  +--------------------+    +---------------------------+    +------------------+  |
+-----------------------------------------------------------------------------------+
```

---

## 3. High-Level Component Breakdown

### A. Core Engine (`dqs/core/`)

#### 1. `analyzer.py` (AST SQL Analyzer & N+1 Detector)
- **`fingerprint(sql)`**: Leverages `sqlglot` to parse raw SQL queries into ASTs. It strips dynamic literals (e.g. IDs, strings), normalizes dynamic `IN (...)` parameter lists, and canonicalizes table aliases (`T0`, `T1`).
- **`detect_n_plus_one(queries, threshold)`**: Groups queries by a composite key of `(SQL Fingerprint, source_location)` and flags N+1 patterns that exceed the threshold.
- **`suggest_fix(fingerprint, relationships)`**: Generates copy-pasteable Django ORM fixes (such as `.select_related()` or `.prefetch_related()`).

#### 2. `targets.py` (Unified Target Dataclass)
- Defines the `Target` dataclass (`id`, `kind`, `triggerable`, `trigger_spec`, `static_findings`).
- Provides a unified shape for HTTP views, signals, Celery tasks, and background functions.

#### 3. `static_advisor.py` (Framework-Agnostic AST Advisor)
- Scans user python code statically without importing or executing it.
- **ORM Call in Loop**: Detects `.filter()`, `.get()`, `.all()` calls inside `for` loops.
- **Blocking Calls**: Detects synchronous I/O (`requests.get`, `smtplib.SMTP`, `time.sleep`) and resolves `import X as Y` and `from X import Y` aliases.

---

### B. Django Adapter (`dqs/adapters/drf/`)

#### 1. `execution/discovery.py` (Target Discovery Engine)
- Discovers URL endpoints (`DjangoIntrospector`), Django signals (`post_save`, `pre_save`, `post_delete`), Celery tasks, and Channels ASGI consumers.
- Integrates static schema advisor checks (`schema_advisor.py`) for PK strategies and missing index detection.
- Populates `Target` instances and passes callables through `StaticASTAdvisor`.

#### 2. `routing/introspector.py` (Route & URL Introspector)
- Recursively walks Django's `urlpatterns` tree.
- Categorizes views into DRF `ViewSet`, `APIView`, or standard Django function/class-based views.
- Safely reports `executable=False` when routes cannot be resolved statically.

#### 3. `execution/query_interceptor.py` (DB-Driver Boundary Interceptor)
- Context manager hooking into Django's `connection.execute_wrapper()`.
- Captures SQL, execution duration, and walks `inspect.stack()` to attribute each query to exact user code line numbers.

#### 4. `routing/converters.py` (Dynamic Path Converter Resolver)
- Extracts URL path converters (`int`, `slug`, `uuid`, `str`, `path`).
- Uses model lookup or `model_bakery` mock seeding to supply concrete values for parameterized endpoints.

#### 5. `mocking/generator.py` (Mock Data & Request Payload Engine)
- `model_bakery` wrapper with constraint safety for relationship seeding.
- Automatically infers DRF serializer and Django form payloads for `POST`/`PUT`/`PATCH` profiling.

#### 6. `execution/runner.py` (Sandbox Execution Engine)
- **`profile_callable()`**: Runs callables inside a `transaction.atomic()` savepoint with the `QueryInterceptor` active. Executes setup callables (such as mock data seeding) inside the rollback boundary prior to query interception to keep query counts clean.
- **`execute_isolated()`**: Simulates HTTP requests via `RequestFactory` and rolls back all database mutations.

#### 7. `execution/schema_advisor.py` (Schema & Index Advisor)
- Analyzes Django ORM models to detect auto-increment PK strategies (recommends UUIDv7).
- Cross-references queried fields against model indexes to flag missing indexes.

---

## 4. Directory Structure Overview

```
dqs/
├── __init__.py
├── core/                              # Framework-agnostic engine (Zero Django imports)
│   ├── analyzer.py                    # sqlglot-based SQL AST fingerprinting & N+1 detection
│   ├── static_advisor.py              # Pure AST static code advisor (loops, blocking I/O)
│   └── targets.py                     # Unified Target dataclass
└── adapters/
    └── drf/                           # Django & DRF adapter
        ├── __init__.py
        ├── apps.py                    # DQS Django AppConfig (DEBUG guard)
        ├── router.py                  # Shadow DB router & profiling_session context manager
        ├── types.py                   # Shared dataclasses (PathParam, RouteMetadata, ExecutionResult, SeedDataRequiredError)
        ├── views.py                   # Dashboard & AJAX profiling endpoints
        ├── urls.py                    # URL configuration (/dqs/, /dqs/profile/)
        ├── database/
        │   └── db_manager.py          # Shadow DB validation & migration runner
        ├── routing/
        │   ├── introspector.py        # URL route pattern tree walker
        │   └── converters.py          # Dynamic path converter & parameter resolution
        ├── mocking/
        │   └── generator.py           # Model Bakery wrapper & body inference
        └── execution/
            ├── discovery.py           # Target discovery (views, signals, tasks, consumers)
            ├── query_interceptor.py   # DB connection.execute_wrapper hook + QueryAnalysisEngine
            ├── runner.py              # Savepoint execution & callable profiling
            └── schema_advisor.py      # Database schema & PK strategy recommendations
```

---

## 5. Class Sequence Diagrams

### 5.1 Core Classes

#### 5.1.1 `dqs.core.targets.Target` (Dataclass)

```mermaid
sequenceDiagram
    autonumber
    participant Client as Client Code
    participant Target as Target Dataclass
    
    Client->>Target: Create Target(id, kind, triggerable, trigger_spec, static_findings)
    Note right of Target: Fields:<br/>- id: str (e.g. "view:/api/books/")<br/>- kind: Literal["view","signal","task","consumer","static_only"]<br/>- triggerable: bool<br/>- trigger_spec: dict | None<br/>- static_findings: list[dict]
    Target-->>Client: Returns Target instance
```

#### 5.1.2 `dqs.core.analyzer.AST Analyzer`

```mermaid
sequenceDiagram
    autonumber
    participant Client as Client Code
    participant Analyzer as analyzer.py Functions
    participant SQLGlot as sqlglot Parser
    
    Client->>Analyzer: fingerprint(raw_sql)
    Analyzer->>SQLGlot: parse_one(raw_sql)
    SQLGlot-->>Analyzer: Parsed AST
    Analyzer->>Analyzer: Strip literals to "?"
    Analyzer->>Analyzer: Collapse IN(...) to "?"
    Analyzer->>Analyzer: Canonicalize table aliases (T0, T1)
    Analyzer->>Analyzer: Sort WHERE conditions
    Analyzer-->>Client: Normalized SQL fingerprint string
    
    Client->>Analyzer: detect_n_plus_one(queries, threshold)
    Analyzer->>Analyzer: fingerprint() each query
    Analyzer->>Analyzer: Group by fingerprint
    Analyzer->>Analyzer: Filter groups >= threshold
    Analyzer->>Analyzer: suggest_fix() for each flagged group
    Analyzer-->>Client: List of N+1 flags with suggestions
```

#### 5.1.3 `dqs.core.static_advisor.StaticASTAdvisor`

```mermaid
sequenceDiagram
    autonumber
    participant Client as Client Code
    participant Advisor as StaticASTAdvisor
    participant AST as Python AST Parser
    
    Client->>Advisor: StaticASTAdvisor(source_code, filename)
    Client->>Advisor: run()
    Advisor->>AST: ast.parse(source_code)
    AST-->>Advisor: AST Tree
    
    loop Visit AST Nodes
        Advisor->>Advisor: visit_Import / visit_ImportFrom
        Note right of Advisor: Build import_map for alias resolution
        
        Advisor->>Advisor: visit_For / visit_AsyncFor / visit_While
        Note right of Advisor: Track _loop_depth++
        
        Advisor->>Advisor: visit_Call
        Note right of Advisor: Check ORM call in loop<br/>Check blocking I/O calls<br/>Collect queried fields
    end
    
    Advisor-->>Client: List of findings (ORM_CALL_IN_LOOP, BLOCKING_EXTERNAL_CALL)
```

---

### 5.2 Django Adapter Classes

#### 5.2.1 `dqs.adapters.drf.routing.introspector.DjangoIntrospector`

```mermaid
sequenceDiagram
    autonumber
    participant Client as Client Code
    participant Introspector as DjangoIntrospector
    participant Django as Django URL Resolver
    participant RouteMeta as RouteMetadata
    
    Client->>Introspector: DjangoIntrospector()
    Note right of Introspector: Validates DEBUG=True
    
    Client->>Introspector: list_all_routes()
    Introspector->>Django: get_resolver().url_patterns
    Django-->>Introspector: Root URL patterns
    
    loop Recursive _extract_patterns
        Introspector->>Introspector: _get_clean_path() - normalize route
        alt URLResolver
            Introspector->>Introspector: Recurse into url_patterns
        else URLPattern
            Introspector->>Introspector: _analyze_view()
            Note right of Introspector: Extract model via 5 strategies<br/>Extract path params<br/>Extract lookup_map<br/>Determine view_type & executable
            Introspector->>RouteMeta: Create RouteMetadata
            RouteMeta-->>Introspector: RouteMetadata instance
            Introspector->>Introspector: Append to routes list
        end
    end
    
    Introspector-->>Client: List[RouteMetadata]
```

#### 5.2.2 `dqs.adapters.drf.routing.converters.PathConverterResolver`

```mermaid
sequenceDiagram
    autonumber
    participant Client as Client Code
    participant Resolver as PathConverterResolver
    participant Django as Django ORM / model_bakery
    participant RouteMeta as RouteMetadata
    
    Client->>Resolver: build_executable_url(route, explicit_params)
    Resolver->>Resolver: resolve_params_for_route()
    Note right of Resolver: Get missing params from route.path_params
    
    alt Has target_model
        Resolver->>Django: Query model.objects.first() (shadow DB)
        alt Record exists
            Django-->>Resolver: Model instance
            Resolver->>Resolver: extract_from_model_instance() using lookup_map
        else No record & auto_generate
            Resolver->>Django: ModelBakeryGenerator.ensure_capped_seeding()
            Django-->>Resolver: Seeded instance
            Resolver->>Resolver: Extract params from instance
        end
    end
    
    Resolver->>Resolver: render_concrete_url() via reverse() or regex substitution
    Resolver-->>Client: (concrete_url, resolved_params, created_instance)
```

#### 5.2.3 `dqs.adapters.drf.mocking.generator.ModelBakeryGenerator`

```mermaid
sequenceDiagram
    autonumber
    participant Client as Client Code
    participant Generator as ModelBakeryGenerator
    participant Baker as model_bakery
    participant DB as Database (Shadow or Default)
    
    Client->>Generator: generate(model, quantity, commit=True)
    Generator->>Generator: _resolve_model() - get Model class
    Generator->>Generator: _sample_existing_fields() - read existing record template
    Generator->>Generator: _build_uniqueness_overrides() - generate unique values for PK/unique fields
    
    alt commit=True
        Generator->>Baker: baker.make(model, _quantity, _using=db_alias, **overrides)
    else
        Generator->>Baker: baker.prepare(model, _quantity, **overrides)
    end
    
    alt Success
        Baker-->>Generator: List of model instances
        Generator->>Generator: Cache in _sample_cache
        Generator-->>Client: List of model instances
    else ModelBakeryException
        Generator->>Generator: _recovery_generate() with _fill_optional, _save_related
        alt Recovery Success
            Generator-->>Client: List of model instances
        else Recovery Failed
            Generator-->>Client: Raises SeedDataRequiredError
        end
    end
```

#### 5.2.4 `dqs.adapters.drf.execution.query_interceptor.QueryInterceptor`

```mermaid
sequenceDiagram
    autonumber
    participant Client as Client Code (runner)
    participant Interceptor as QueryInterceptor
    participant DjangoDB as django.db.connection
    participant Stack as inspect.stack()
    
    Client->>Interceptor: with QueryInterceptor() as interceptor:
    Interceptor->>DjangoDB: connection.execute_wrapper(_wrapper)
    
    loop Each SQL Query Execution
        DjangoDB->>Interceptor: _wrapper(execute, sql, params, many, context)
        Interceptor->>Interceptor: start_time = perf_counter()
        Interceptor->>DjangoDB: execute(sql, params, many, context)
        DjangoDB-->>Interceptor: Query result
        Interceptor->>Interceptor: duration = perf_counter() - start_time
        Interceptor->>Stack: inspect.stack()
        Stack-->>Interceptor: Call frames
        Interceptor->>Interceptor: _extract_source_location() - skip framework frames
        Interceptor->>Interceptor: Append {sql, time_ms, src_loc} to captured_queries
    end
    
    Client->>Interceptor: Exit context manager
    Interceptor->>DjangoDB: __exit__ - remove wrapper
    Interceptor-->>Client: captured_queries available
```

#### 5.2.5 `dqs.adapters.drf.execution.query_interceptor.QueryAnalysisEngine`

```mermaid
sequenceDiagram
    autonumber
    participant Runner as DjangoSandboxRunner
    participant Engine as QueryAnalysisEngine
    participant Analyzer as dqs.core.analyzer
    
    Runner->>Engine: build_result(route, status_code, queries_captured, ...)
    Engine->>Engine: parse_response_body() - extract JSON from response
    
    loop Format each query
        Engine->>Analyzer: fingerprint(q.sql)
        Analyzer-->>Engine: Normalized fingerprint
        Engine->>Engine: Build formatted_queries list
    end
    
    Engine->>Analyzer: detect_n_plus_one(formatted_queries, threshold=3)
    Analyzer-->>Engine: N+1 flags with suggestions
    Engine->>Engine: Calculate metrics (total_time, db_time, query_count, unique_fingerprints)
    Engine->>Engine: Create ExecutionResult dataclass
    Engine-->>Runner: ExecutionResult
```

#### 5.2.6 `dqs.adapters.drf.execution.runner.DjangoSandboxRunner`

```mermaid
sequenceDiagram
    autonumber
    participant Client as Client Code
    participant Runner as DjangoSandboxRunner
    participant Router as profiling_session / DQSRouter
    participant Seeder as ModelBakeryGenerator
    participant Converter as PathConverterResolver
    participant Interceptor as QueryInterceptor
    participant Analysis as QueryAnalysisEngine
    participant Django as Django / DRF
    
    Client->>Runner: execute_isolated(url, method, path_params, ...)
    Runner->>Router: with profiling_session():
    
    alt target_model provided
        Runner->>Seeder: ensure_capped_seeding(target_model)
        Seeder-->>Runner: Seeded records info
    end
    
    Runner->>Converter: build_executable_url(route_meta, path_params)
    Converter-->>Runner: (resolved_url, resolved_params, created_instance)
    
    Runner->>Runner: RequestSpecBuilder.build() - create request contract
    
    Runner->>Django: resolve(resolved_url) - get view callable
    Runner->>Runner: StaticAnalysisService.detect_side_effects(view_func)
    
    Runner->>Runner: profile_callable(_sandbox_execution, setup=_seed)
    
    alt Shadow DB Active (DQSRouter.is_active)
        Runner->>Seeder: setup() - seed mock data
        Runner->>Interceptor: with QueryInterceptor():
        Runner->>Django: Execute view via RequestFactory
        Interceptor-->>Runner: captured_queries, db_duration
    else Default DB (Atomic Savepoint)
        Runner->>Django: transaction.atomic() + savepoint()
        Runner->>Seeder: setup() - seed mock data
        Runner->>Interceptor: with QueryInterceptor():
        Runner->>Django: Execute view via RequestFactory
        Interceptor-->>Runner: captured_queries, db_duration
        Runner->>Django: savepoint_rollback()
    end
    
    Runner->>Analysis: build_result(route, queries, durations, ...)
    Analysis-->>Runner: ExecutionResult
    Runner-->>Client: ExecutionResult
```

#### 5.2.7 `dqs.adapters.drf.execution.discovery.DjangoTargetDiscovery`

```mermaid
sequenceDiagram
    autonumber
    participant Client as Client Code
    participant Discovery as DjangoTargetDiscovery
    participant Introspector as DjangoIntrospector
    participant SchemaAdv as schema_advisor
    participant StaticAdv as StaticASTAdvisor
    participant Celery as Celery App
    participant Channels as ASGI Application
    participant Target as dqs.core.targets.Target
    
    Client->>Discovery: discover_all()
    
    Note over Discovery: 1. Discover URL Routes
    Discovery->>Introspector: list_all_routes()
    Introspector-->>Discovery: List[RouteMetadata]
    
    loop For each route
        Discovery->>SchemaAdv: check_pk_strategy(route.target_model)
        Discovery->>StaticAdv: StaticASTAdvisor(view_source).run()
        Discovery->>SchemaAdv: check_missing_indexes(target_model, queried_fields)
        Discovery->>Target: Create Target(id="view:path", kind="view", ...)
    end
    
    Note over Discovery: 2. Discover Celery Tasks
    Discovery->>Celery: current_app.tasks.items()
    Celery-->>Discovery: Task registry
    loop For each task
        Discovery->>StaticAdv: _analyze_callable_statically(task_func)
        Discovery->>Target: Create Target(id="task:name", kind="task", ...)
    end
    
    Note over Discovery: 3. Discover Channels Consumers
    Discovery->>Channels: ASGI_APPLICATION -> websocket routes
    Channels-->>Discovery: Consumer routes
    loop For each consumer
        Discovery->>StaticAdv: _analyze_callable_statically(consumer_class)
        Discovery->>Target: Create Target(id="consumer:name", kind="consumer", triggerable=False)
    end
    
    Discovery-->>Client: List[Target]
```

#### 5.2.8 `dqs.adapters.drf.router.DQSRouter` & `profiling_session`

```mermaid
sequenceDiagram
    autonumber
    participant Client as Client Code
    participant Session as profiling_session()
    participant Router as DQSRouter
    participant ThreadLocal as threading.local
    participant Django as Django DB Router
    
    Client->>Session: with profiling_session():
    Session->>Router: DQSRouter.set_active(True)
    Router->>ThreadLocal: _local.active = True
    
    Note over Client: Django ORM operations now route to dqs_shadow DB
    
    Client->>Django: Model.objects.create(...)
    Django->>Router: db_for_read/write(model)
    Router->>Router: is_active() == True
    Router-->>Django: Return "dqs_shadow"
    Django->>Django: Execute on shadow database
    
    Client->>Session: Exit context
    Session->>Router: DQSRouter.set_active(False)
    Router->>ThreadLocal: _local.active = False
```

---

## 6. End-to-End Execution Sequence

```mermaid
sequenceDiagram
    autonumber
    participant Dev as Developer / AI Agent
    participant Disc as Target Discovery Engine
    participant Adv as Static AST Advisor
    participant Conv as Converter & Body Inferrer
    participant Run as Sandbox Runner
    participant DB as Query Interceptor & DB
    participant Ana as AST Analyzer

    Dev->>Disc: Request all targets
    Disc->>Adv: Statically analyze view / signal / task AST
    Adv-->>Disc: Return static findings (e.g. ORM call in loop)
    Disc-->>Dev: List of Target objects

    Dev->>Conv: Resolve path params & infer request body
    Conv-->>Dev: Concrete executable URL & mock JSON payload

    Dev->>Run: execute_isolated(target_id)
    Run->>DB: Open transaction.atomic() savepoint
    Run->>Run: Setup phase (Seed mock data in pre-interception boundary)
    Run->>DB: Attach QueryInterceptor to DB driver connection
    Run->>Run: Dispatch RequestFactory HTTP request to endpoint view
    DB-->>Run: Record queries, execution times, and call stack origins
    Run->>DB: Execute savepoint_rollback()
    Run->>Ana: Pass captured queries & locations
    Ana-->>Dev: Return N+1 flags, SQL fingerprints, and ORM fixes
```

---

## 7. Security & Isolation Model

- **Safe Rollbacks**: Every query execution occurs strictly inside an atomic savepoint. No writes persist to disk or database tables.
- **`DEBUG=True` Guardrail**: Enforces that profiling runs only in development environments.
- **Sanitized SQL**: AST fingerprinting strips user data/literals before rendering analysis reports.
- **Shadow Database**: Optional isolated database (`dqs_shadow`) for profiling to keep development database clean.

---

## 8. Installation & Testing

### Development Installation

```bash
# From source (editable install)
pip install -e "C:\Users\mprof\OneDrive\Desktop\da-profiler"

# Or build and install
pip install dist/da_profiler-0.3.0-py3-none-any.whl
```

### Demo Project Setup

```bash
# 1. Go to demo project
cd demos/drf

# 2. Install dependencies
pip install -e "..[django]"

# 3. Configure settings (DEBUG=True, dqs_shadow DB, DATABASE_ROUTERS)

# 4. Run migrations on shadow DB
python manage.py migrate --database=dqs_shadow

# 5. Run tests
pytest -m core        # Pure Python tests (fast, no DB)
pytest -m django      # Django/DRF adapter tests (requires DB)
pytest                # All tests
```

### Using in Your Own Project

```bash
# Install from PyPI
pip install da-profiler[django]

# Add to settings.py (development only)
if DEBUG:
    INSTALLED_APPS += ["dqs.adapters.drf"]
    DATABASE_ROUTERS = ["dqs.adapters.drf.router.DQSRouter"]

# Configure shadow database
DATABASES = {
    "default": {...},
    "dqs_shadow": {...},  # Same engine as default
}

# Run shadow migrations
python manage.py migrate --database=dqs_shadow
```

---

## 9. Key Data Flow Summary

| Stage | Input | Component | Output |
|-------|-------|-----------|--------|
| **Discovery** | Django URL patterns | `DjangoIntrospector` | `List[RouteMetadata]` |
| **Target Creation** | Routes + AST analysis | `DjangoTargetDiscovery` | `List[Target]` |
| **Parameter Resolution** | Route + explicit params | `PathConverterResolver` | Concrete URL + params |
| **Mock Seeding** | Target model | `ModelBakeryGenerator` | DB records (shadow) |
| **Execution** | URL + method + params | `DjangoSandboxRunner` | HTTP response + queries |
| **Interception** | DB queries | `QueryInterceptor` | Queries with src_loc |
| **Analysis** | Captured queries | `QueryAnalysisEngine` + `analyzer.py` | N+1 flags + ORM fixes |
| **Result** | All above | `ExecutionResult` | Structured profiling report |

---

## 10. Complete Flow Diagrams

For detailed visual flow diagrams covering:
- Route discovery & dashboard loading
- Complete profiling execution (button click to results)
- Mock data seeding decision tree
- Query interception & N+1 detection
- High-level component interactions
- Simplified flow summary

See **[Flow Diagrams](./docs/flow-diagrams.md)**.