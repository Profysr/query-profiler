# ❓ Frequently Asked Questions (FAQ)

---

## 1. How is Da Profiler different from Django Debug Toolbar or Django Silk?

| Feature | Django Debug Toolbar / Silk | Da Profiler |
| :--- | :--- | :--- |
| **Execution Mode** | Reactive (log when users click in a browser) | Proactive (automatically discovers & runs endpoints) |
| **Database Overhead** | High (persists log rows to database disk) | Zero (all executions roll back automatically) |
| **N+1 Identification** | Manual (developer reads raw SQL) | Automated (AST SQL fingerprinting via `sqlglot`) |
| **Fix Guidance** | Raw SQL output | Prescriptive ORM fix (`.select_related()` code snippet) |
| **AI Agent Support** | None | Native MCP Server (stdio / SSE) for Cursor / Claude |

---

## 2. Is Da Profiler safe to run on my database?

**Yes!** Da Profiler executes all profiling runs inside an isolated `transaction.atomic()` savepoint. 

The moment an endpoint completes, Da Profiler triggers an immediate `savepoint_rollback()`. Any records created, modified, or deleted by the endpoint during the profiling run are erased instantly.

---

## 3. Can I run Da Profiler in Production?

> [!CAUTION]
> **No.** Da Profiler enforces a strict `DEBUG = True` check in its AppConfig. It is designed for development environments, CI/CD pipelines, and AI agent optimization loops. Running profiling engines in production is not recommended.

---

## 4. Does Da Profiler work with Django REST Framework (DRF)?

**Yes!** Da Profiler has first-class adapter support for DRF `APIView`, `ViewSet`, `GenericAPIView`, and standard Django Function-Based (FBV) and Class-Based Views (CBV).

---

## 5. How does Da Profiler support AI Coding Agents (Cursor, Claude, Windsurf)?

Da Profiler includes a native Model Context Protocol (MCP) server. AI agents can call Da Profiler tools directly:
1. `list_django_routes`: Discovers all endpoints.
2. `profile_endpoint`: Profiles an endpoint and returns AST fingerprints + suggested fixes.
3. The agent rewrites the Django view code.
4. `profile_endpoint`: Re-runs profiling to verify that query count dropped (e.g. from 45 queries down to 2).

---
