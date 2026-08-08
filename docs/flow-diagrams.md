# Da Profiler — Complete Execution Flow Diagrams

This document provides comprehensive flow diagrams showing how Da Profiler works end-to-end, from route discovery to profiling execution with automatic mock data seeding.

---

## 1. Route Discovery & Dashboard Loading Flow

```mermaid
flowchart TD
    %% User Action
    User["👤 User opens /dqs/ dashboard"] --> DashboardView["DQSDashboardView.get()"]
    
    %% Introspection Process
    DashboardView --> Introspector["DjangoIntrospector()"]
    Introspector -->|Validates DEBUG=True| DebugCheck{"DEBUG=True?"}
    DebugCheck -->|No| Forbidden["🚫 HTTP 403 Forbidden"]
    DebugCheck -->|Yes| GetResolver["get_resolver().url_patterns"]
    
    %% Recursive URL Pattern Walking
    GetResolver --> WalkPatterns["_extract_patterns() recursive walk"]
    WalkPatterns --> PatternLoop{"For each pattern"}
    PatternLoop -->|URLResolver| Recurse["Recurse into url_patterns"]
    PatternLoop -->|URLPattern| CheckPath{"Path starts with /dqs/?"}
    CheckPath -->|Yes| Skip["Skip internal routes"]
    CheckPath -->|No| AnalyzeView["_analyze_view()"]
    
    %% View Analysis
    AnalyzeView --> ExtractCallback["pattern.callback"]
    ExtractCallback --> Unwrap["inspect.unwrap()"]
    Unwrap --> GetViewClass["Extract view_class/cls"]
    GetViewClass --> CheckDRF{"Is DRF APIView/ViewSet?"}
    CheckDRF -->|No| SkipNonDRF["Skip non-DRF views"]
    CheckDRF -->|Yes| ExtractModel["_extract_model_from_class() - 5 strategies"]
    ExtractModel --> ExtractParams["_extract_path_params()"]
    ExtractParams --> ExtractLookup["_extract_view_lookup_map()"]
    ExtractLookup --> DetermineType{"ViewSet or APIView?"}
    DetermineType -->|ViewSet| ViewSetMethods["Read callback.actions"]
    DetermineType -->|APIView| APIViewMethods["Check http_method_names overrides"]
    ViewSetMethods --> BuildMeta["Create RouteMetadata"]
    APIViewMethods --> BuildMeta
    
    %% Result
    BuildMeta --> CollectRoutes["Append to routes list"]
    CollectRoutes --> ReturnRoutes["Return List[RouteMetadata]"]
    ReturnRoutes --> RenderTemplate["render('dqs/dashboard.html')"]
    RenderTemplate --> Dashboard["📊 Dashboard with route list"]
```

---

## 2. Complete Profiling Execution Flow (When "Run Profiler" is Clicked)

```mermaid
flowchart TD
    %% Entry Point
    Click["🖱️ User clicks 'Run Profiler' on /dqs/"] --> AJAXPost["POST /dqs/profile/ with JSON body"]
    AJAXPost --> ProfileView["DQSProfileView.post()"]
    ProfileView --> ValidateDebug{"DEBUG=True?"}
    ValidateDebug -->|No| Forbidden403["🚫 HTTP 403"]
    ValidateDebug -->|Yes| ParseBody["json.loads(request.body)"]
    ParseBody --> ExtractParams["Extract: route, method, path_params, seed_count, target_model"]
    
    %% Initialize Runner
    ExtractParams --> InitRunner["DjangoSandboxRunner()"]
    InitRunner --> ShadowDBMgr["ShadowDatabaseManager.ensure_initialized()"]
    ShadowDBMgr --> ValidateConfig["validate_configuration()"]
    ValidateConfig --> CheckShadowDB{"dqs_shadow in DATABASES?"}
    CheckShadowDB -->|No| ConfigError["❌ ImproperlyConfigured"]
    CheckShadowDB -->|Yes| CheckRouter{"DQSRouter in DATABASE_ROUTERS?"}
    CheckRouter -->|No| RouterError["❌ ImproperlyConfigured"]
    CheckRouter -->|Yes| RunMigrations["call_command migrate --database=dqs_shadow"]
    RunMigrations --> CreateFactory["APIRequestFactory()"]
    CreateFactory --> RunnerReady["Runner initialized"]
    
    %% Execute Isolated
    RunnerReady --> ExecuteIsolated["runner.execute_isolated()"]
    ExecuteIsolated --> ProfilingSession["with profiling_session():"]
    
    %% Shadow DB Activation
    ProfilingSession --> ActivateRouter["DQSRouter.set_active(True)"]
    ActivateRouter --> ThreadLocal["threading.local.active = True"]
    
    %% Step 1: Ensure Minimum Seeding (Capped Seeding)
    ThreadLocal --> CheckTargetModel{"target_model provided?"}
    CheckTargetModel -->|Yes| CappedSeeding["ModelBakeryGenerator.ensure_capped_seeding()"]
    CheckTargetModel -->|No| SkipCappedSeeding["Skip capped seeding"]
    
    CappedSeeding --> CountCheck["Count records in shadow DB"]
    CountCheck --> BelowThreshold{"count < SEED_MIN_THRESHOLD (1)?"}
    BelowThreshold -->|Yes| SeedUpToCap["Seed up to SEED_MAX_CAP (50) records"]
    BelowThreshold -->|No| SkipSeeding["Already enough records"]
    SeedUpToCap --> GenerateMocks["ModelBakeryGenerator.generate()"]
    SkipSeeding --> GenerateMocks
    GenerateMocks --> SeededRecords["Return seeded records info"]
    
    %% Step 2: Resolve Path Parameters
    SeededRecords --> BuildRouteMeta["Build RouteMetadata from route"]
    BuildRouteMeta --> ResolveParams["PathConverterResolver.build_executable_url()"]
    
    ResolveParams --> ExtractMissingParams["Find missing path_params"]
    ExtractMissingParams --> HasParams{"Has path params?"}
    HasParams -->|No| DirectURL["Use route path directly"]
    HasParams -->|Yes| ResolveEachParam["For each missing param:"]
    
    ResolveEachParam --> CheckModel{"target_model valid?"}
    CheckModel -->|No| ParamError["❌ SeedDataRequiredError"]
    CheckModel -->|Yes| QueryShadowDB["model.objects.using('dqs_shadow').first()"]
    QueryShadowDB --> FoundRecord{"Record exists?"}
    FoundRecord -->|Yes| ExtractValue["extract_from_model_instance() with lookup_map"]
    FoundRecord -->|No| AutoGenerate{"auto_generate_if_missing?"}
    AutoGenerate -->|No| ParamError
    AutoGenerate -->|Yes| SeedFallback["ModelBakeryGenerator.ensure_capped_seeding()"]
    SeedFallback --> NewRecord["Get newly seeded record"]
    NewRecord --> ExtractValue
    
    ExtractValue --> AllResolved{"All params resolved?"}
    AllResolved -->|No| ParamError
    AllResolved -->|Yes| RenderURL["render_concrete_url() via reverse() or regex"]
    RenderURL --> ConcreteURL["✅ Concrete executable URL"]
    
    %% Step 3: Build Request Spec
    ConcreteURL --> BuildSpec["RequestSpecBuilder.build()"]
    BuildSpec --> CheckUnresolved{"Any UNRESOLVED params?"}
    CheckUnresolved -->|Yes| HandoverError["❌ Return 400 with unresolved params"]
    CheckUnresolved -->|No| ResolveMatch["resolve(concrete_url)"]
    
    %% Step 4: Side Effect Analysis
    ResolveMatch --> SideEffectCheck["StaticAnalysisService.detect_side_effects()"]
    SideEffectCheck --> GetSource["inspect.getsource(view_func)"]
    GetSource --> RunASTAdvisor["StaticASTAdvisor(source).run()"]
    RunASTAdvisor --> CollectWarnings["Collect BLOCKING_EXTERNAL_CALL findings"]
    CollectWarnings --> SideEffectWarnings["side_effect_warnings list"]
    
    %% Step 5: Execute in Sandbox
    SideEffectWarnings --> ProfileCallable["profile_callable(_sandbox_execution, setup=_seed)"]
    
    ProfileCallable --> RouterCheck{"DQSRouter.is_active()?"}
    RouterCheck -->|Yes| ShadowMode["Shadow DB Mode"]
    RouterCheck -->|No| DefaultMode["Default DB + Savepoint Mode"]
    
    %% Shadow DB Mode
    ShadowMode --> SetupSeed["_seed() - seed additional if seed_count > 0"]
    SetupSeed --> WithInterceptor["with QueryInterceptor():"]
    WithInterceptor --> ExecView["Execute view via RequestFactory"]
    
    %% Default DB Mode
    DefaultMode --> Atomic["transaction.atomic()"]
    Atomic --> Savepoint["transaction.savepoint()"]
    Savepoint --> TryBlock["try:"]
    TryBlock --> SetupSeed2["_seed()"]
    SetupSeed2 --> WithInterceptor2["with QueryInterceptor():"]
    WithInterceptor2 --> ExecView2["Execute view via RequestFactory"]
    ExecView2 --> Finally["finally:"]
    Finally --> Rollback["transaction.savepoint_rollback(sid)"]
    
    %% Query Interception (Both Modes)
    ExecView --> InterceptQueries["QueryInterceptor captures:"]
    ExecView2 --> InterceptQueries
    InterceptQueries --> CaptureSQL["SQL + time_ms + src_loc (via inspect.stack)"]
    CaptureSQL --> ReturnQueries["Return captured_queries"]
    
    %% Step 6: Analyze & Build Result
    ReturnQueries --> QueryAnalysis["QueryAnalysisEngine.build_result()"]
    QueryAnalysis --> FormatQueries["Format each query with fingerprint()"]
    FormatQueries --> DetectNPlusOne["detect_n_plus_one(formatted_queries, threshold=3)"]
    DetectNPlusOne --> GroupByFP["Group by fingerprint + src_loc"]
    GroupByFP --> CheckThreshold{"count >= 3 & SELECT?"}
    CheckThreshold -->|Yes| SuggestFix["suggest_fix() with relationships"]
    CheckThreshold -->|No| NoFlag["No N+1 flag"]
    SuggestFix --> BuildAnalysis["Build analysis payload"]
    NoFlag --> BuildAnalysis
    BuildAnalysis --> CalcMetrics["Calculate: total_time, db_time, query_count, unique_fps"]
    CalcMetrics --> BuildResult["Create ExecutionResult dataclass"]
    
    %% Return Response
    BuildResult --> JSONResponse["JsonResponse with DQSJSONEncoder"]
    JSONResponse --> Frontend["📊 Frontend displays results"]
    
    %% Cleanup
    Frontend --> DeactivateRouter["DQSRouter.set_active(False)"]
    DeactivateRouter --> ThreadLocalClear["threading.local.active = False"]
    ThreadLocalClear --> Done["✅ Profiling complete"]
    
    %% Error Paths
    ConfigError --> JSONResponse
    RouterError --> JSONResponse
    ParamError --> JSONResponse
    HandoverError --> JSONResponse
```

---

## 3. Mock Data Seeding Decision Flow

```mermaid
flowchart TD
    Start["Need parameter value for URL"] --> CheckExplicit{"Explicit param provided?"}
    CheckExplicit -->|Yes| UseExplicit["Use provided value"]
    CheckExplicit -->|No| CheckModel{"target_model resolved?"}
    
    CheckModel -->|No| Error1["❌ SeedDataRequiredError: Cannot resolve model"]
    CheckModel -->|Yes| QueryDB["Query shadow DB for existing record"]
    
    QueryDB --> Found{"Record found?"}
    Found -->|Yes| Extract["Extract param via lookup_map"]
    Found -->|No| CheckAutoGen{"auto_generate_if_missing=True?"}
    
    CheckAutoGen -->|No| Error2["❌ SeedDataRequiredError: Provide 2-3 records manually"]
    CheckAutoGen -->|Yes| SeedCapped["ModelBakeryGenerator.ensure_capped_seeding()"]
    
    SeedCapped --> CountCheck{"Current count < min_threshold?"}
    CountCheck -->|Yes| Generate["model_bakery generate() with uniqueness overrides"]
    CountCheck -->|No| UseExisting["Use existing record"]
    
    Generate --> PrimaryTry["baker.make() with overrides"]
    PrimaryTry --> Success{"Success?"}
    Success -->|Yes| Cache["Cache in _sample_cache"]
    Success -->|No| Recovery["Recovery: _fill_optional=True, _save_related=True"]
    Recovery --> RecoverySuccess{"Success?"}
    RecoverySuccess -->|Yes| Cache
    RecoverySuccess -->|No| Error3["❌ SeedDataRequiredError: Manual records needed"]
    
    Cache --> Extract
    UseExisting --> Extract
    Extract --> Done["✅ Param resolved"]
    UseExplicit --> Done
    
    Error1 --> Manual["User provides JSON records via clone_user_records()"]
    Error2 --> Manual
    Error3 --> Manual
    Manual --> Validate["Validate via DRF Serializer or ORM"]
    Validate --> Clone["Clone to reach target quantity"]
    Clone --> Done
```

---

## 4. Query Interception & N+1 Detection Flow

```mermaid
flowchart TD
    Execute["View executes ORM queries"] --> Wrapper["QueryInterceptor._wrapper() called"]
    Wrapper --> TimerStart["start = perf_counter()"]
    TimerStart --> ExecSQL["execute(sql, params, many, context)"]
    ExecSQL --> TimerEnd["duration = perf_counter() - start"]
    TimerEnd --> StackTrace["inspect.stack()"]
    StackTrace --> FilterFrames["Filter out: site-packages, django/, rest_framework/, dqs/"]
    FilterFrames --> FindUserFrame["Find first user code frame"]
    FindUserFrame --> FormatLoc["Format as 'path/file.py:lineno'"]
    FormatLoc --> Store["Append {sql, time_ms, src_loc} to captured_queries"]
    
    %% After execution
    Store --> Analysis["QueryAnalysisEngine.build_result()"]
    Analysis --> FingerprintAll["fingerprint() each query"]
    
    FingerprintAll --> ParseAST["sqlglot.parse_one(sql)"]
    ParseAST --> StripLiterals["Replace all Literals with '?'"]
    StripLiterals --> CollapseIn["Collapse IN (...) to IN (?)"]
    CollapseIn --> CanonicalizeAlias["Canonicalize table aliases to T0, T1..."]
    CanonicalizeAlias --> SortWhere["Sort AND conditions alphabetically"]
    SortWhere --> NormalizedFP["Normalized fingerprint string"]
    
    NormalizedFP --> GroupByFP["Group queries by (fingerprint, src_loc)"]
    GroupByFP --> CountGroups["Count queries per group"]
    CountGroups --> ThresholdCheck{"count >= threshold (3)?"}
    ThresholdCheck -->|Yes| FlagNPlusOne["Flag as N+1"]
    ThresholdCheck -->|No| NoFlag["Not an N+1 pattern"]
    
    FlagNPlusOne --> SuggestFix["suggest_fix(fingerprint, relationships)"]
    SuggestFix --> ParseFP["sqlglot.parse_one(fingerprint)"]
    ParseFP --> GetTable["Extract target table name"]
    GetTable --> CheckRelationships{"relationships mapping provided?"}
    CheckRelationships -->|Yes| LookupRel["Find field_name & rel_type"]
    CheckRelationships -->|No| GenericSuggest["Generic select_related/prefetch_related"]
    LookupRel --> SpecificSuggest[".select_related('field') or .prefetch_related('field')"]
    SpecificSuggest --> BuildPayload["Add to analysis payload"]
    GenericSuggest --> BuildPayload
    NoFlag --> BuildPayload
    
    BuildPayload --> FinalResult["ExecutionResult with analysis array"]
```

---

## 5. High-Level Component Interaction Flow

```mermaid
flowchart LR
    subgraph Frontend["🌐 Frontend (Dashboard)"]
        UI["/dqs/ Dashboard"]
        Button["Run Profiler Button"]
    end
    
    subgraph DjangoViews["📡 Django Views (dqs/adapters/drf/views.py)"]
        DashboardView["DQSDashboardView"]
        ProfileView["DQSProfileView"]
    end
    
    subgraph Introspection["🔍 Route Discovery (routing/)"]
        Introspector["DjangoIntrospector"]
        Converter["PathConverterResolver"]
    end
    
    subgraph Execution["⚙️ Execution Engine (execution/)"]
        Runner["DjangoSandboxRunner"]
        Interceptor["QueryInterceptor"]
        Analysis["QueryAnalysisEngine"]
        Discovery["DjangoTargetDiscovery"]
    end
    
    subgraph MockData["🌱 Mock Data (mocking/)"]
        Generator["ModelBakeryGenerator"]
        BodyInferrer["infer_request_body()"]
    end
    
    subgraph Core["🧠 Core Engine (dqs/core/)"]
        Analyzer["analyzer.py: fingerprint, detect_n_plus_one, suggest_fix"]
        StaticAdvisor["static_advisor.py: StaticASTAdvisor"]
        Targets["targets.py: Target dataclass"]
    end
    
    subgraph Database["🗄️ Database Layer"]
        ShadowDB["dqs_shadow (PostgreSQL)"]
        DefaultDB["default DB"]
        Router["DQSRouter + profiling_session()"]
    end
    
    UI --> DashboardView
    Button --> ProfileView
    
    DashboardView --> Introspector
    Introspector --> Converter
    Introspector --> Discovery
    Discovery --> StaticAdvisor
    Discovery --> Targets
    
    ProfileView --> Runner
    Runner --> Router
    Router --> ShadowDB
    Runner --> Generator
    Generator --> ShadowDB
    Runner --> Converter
    Runner --> BodyInferrer
    Runner --> Interceptor
    Interceptor --> ShadowDB
    Interceptor --> DefaultDB
    Interceptor --> Analysis
    Analysis --> Analyzer
    Runner --> StaticAdvisor
    
    Runner -.->|Savepoint Rollback| DefaultDB
```

---

## 6. Simplified Flow Summary (For Quick Reference)

```mermaid
flowchart TD
    A["👤 User clicks Run Profiler"] --> B["📡 DQSProfileView receives request"]
    B --> C["🔧 DjangoSandboxRunner.execute_isolated()"]
    C --> D["🗄️ profiling_session() activates dqs_shadow router"]
    D --> E{"🎯 target_model provided?"}
    E -->|Yes| F["🌱 ensure_capped_seeding() - seed up to 50 records"]
    E -->|No| G["Skip capped seeding"]
    F --> H["🔗 PathConverterResolver.build_executable_url()"]
    G --> H
    H --> I{"📝 Path params missing?"}
    I -->|Yes| J["🔍 Query shadow DB for existing record"]
    J --> K{"Record exists?"}
    K -->|No| L["🌱 Auto-seed via model_bakery"]
    K -->|Yes| M["📤 Extract param from record"]
    L --> M
    I -->|No| N["✅ Direct URL"]
    M --> O["🔗 Render concrete URL"]
    N --> O
    O --> P["📋 RequestSpecBuilder.build()"]
    P --> Q{"❓ Unresolved params?"}
    Q -->|Yes| R["❌ Return 400 error"]
    Q -->|No| S["🎯 resolve() URL to view"]
    S --> T["🤖 StaticAnalysisService.detect_side_effects()"]
    T --> U["⚡ profile_callable() with QueryInterceptor"]
    U --> V{"🗄️ Shadow DB active?"}
    V -->|Yes| W["📝 Execute in shadow DB"]
    V -->|No| X["🔄 Execute in atomic savepoint + rollback"]
    W --> Y["📊 QueryInterceptor captures SQL + src_loc"]
    X --> Y
    Y --> Z["🧠 QueryAnalysisEngine + analyzer.py detects N+1"]
    Z --> AA["📦 ExecutionResult with metrics & suggestions"]
    AA --> AB["📤 Return JSON to frontend"]
    AB --> AC["📊 Dashboard displays results"]
```

---

## Key Decision Points Summary

| Step | Decision | Yes Path | No Path |
|------|----------|----------|---------|
| 1 | DEBUG=True? | Continue | 403 Forbidden |
| 2 | dqs_shadow in DATABASES? | Continue | Config Error |
| 3 | DQSRouter in DATABASE_ROUTERS? | Continue | Config Error |
| 4 | target_model provided? | Capped seeding | Skip |
| 5 | Records < threshold? | Seed up to cap | Skip |
| 6 | Path params missing? | Resolve each | Direct URL |
| 7 | Record in shadow DB? | Extract param | Auto-seed if enabled |
| 8 | Auto-generate enabled? | model_bakery generate | SeedDataRequiredError |
| 9 | model_bakery primary success? | Use result | Recovery attempt |
| 10 | Recovery success? | Use result | SeedDataRequiredError |
| 11 | All params resolved? | Continue | Return 400 with unresolved |
| 12 | Shadow DB active? | Persist in shadow | Savepoint + rollback |
| 13 | Query count >= threshold? | Flag N+1 + suggest fix | No flag |

---

## Data Flow Summary

```
User Request
    │
    ▼
DQSProfileView (validates DEBUG, parses JSON)
    │
    ▼
DjangoSandboxRunner.execute_isolated()
    │
    ├──► profiling_session() ──► DQSRouter.set_active(True)
    │
    ├──► ModelBakeryGenerator.ensure_capped_seeding() ──► Shadow DB
    │
    ├──► PathConverterResolver.build_executable_url()
    │       ├──► Query shadow DB for existing record
    │       └──► Fallback: model_bakery generate with recovery
    │
    ├──► RequestSpecBuilder.build() ──► Validate params
    │
    ├──► StaticAnalysisService.detect_side_effects() ──► AST scan
    │
    ├──► profile_callable()
    │       ├──► QueryInterceptor (captures SQL + stack trace)
    │       └──► Execute view via RequestFactory
    │
    ├──► QueryAnalysisEngine.build_result()
    │       ├──► analyzer.fingerprint() each query
    │       ├──► analyzer.detect_n_plus_one()
    │       └──► analyzer.suggest_fix()
    │
    ▼
ExecutionResult (dataclass) ──► JSON Response ──► Frontend Dashboard
```

---

*Generated from Da Profiler v0.3.0 source code analysis*