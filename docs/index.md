# Welcome to Da Profiler 🔍

> **Explain Like I'm 5 (ELI5)**: Imagine your web application is a busy restaurant. When a customer orders dinner, the chef has to run back and forth to the pantry 50 times to get one ingredient per plate instead of grabbing them all in one trip! This is called an **N+1 Query Bottleneck**, and it makes your web app slow.
> 
> **Da Profiler** is a super-smart assistant that checks your code, finds every single unnecessary trip to the database pantry, tells you the exact line of code causing it, and gives you a copy-pasteable fix — all without risking or corrupting your real database! 🚀

---

## 🌟 What is Da Profiler?

**Da Profiler** (Python package `dqs`) is an open-source, agentic ORM profiling engine and static code analyzer designed for Django web applications. 

Unlike traditional profiling tools that require you to click through your website while logging data to your database, Da Profiler:

1. **Scans Automatically**: Automatically discovers endpoints, signal receivers, and Celery tasks in your project via [`discovery.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/adapters/drf/discovery.py).
2. **Runs in a Safe Sandbox**: Executes code inside isolated transaction savepoints and rolls them back instantly via [`runner.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/adapters/drf/runner.py). Your database is never touched or modified!
3. **Pinpoints Exact Lines of Code**: Hooks into database drivers to tell you which file and line triggered each query via [`query_interceptor.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/adapters/drf/query_interceptor.py).
4. **Normalizes SQL with AST Engine**: Uses AST parsing (`sqlglot`) to group identical queries together regardless of changing parameters or numbers via [`analyzer.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/core/analyzer.py).
5. **Performs Static Code Analysis**: Scans source code without running it to catch ORM calls in loops and blocking calls via [`static_advisor.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/core/static_advisor.py).
6. **AI Agent Friendly**: Exposes a Model Context Protocol (MCP) tool interface so AI coding assistants (Cursor, Claude, Windsurf) can autonomously detect, fix, and re-verify performance bugs.

---

## 🗺️ What We've Built So Far

Da Profiler has progressed through key development milestones:

| Component / Milestone | Primary Module | What It Does | Status |
| :--- | :--- | :--- | :--- |
| **Core AST SQL Analyzer** | [`dqs/core/analyzer.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/core/analyzer.py) | Parses SQL queries into AST syntax trees, strips literals, collapses `IN (...)` lists, and flags N+1 patterns. | ✅ Complete |
| **Django Route Introspector** | [`dqs/adapters/drf/introspector.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/adapters/drf/introspector.py) | Automatically walks Django URL trees, categorizes DRF ViewSets, APIViews, and standard views. | ✅ Complete |
| **Isolated Sandbox Runner** | [`dqs/adapters/drf/runner.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/adapters/drf/runner.py) | Simulates HTTP requests inside `transaction.atomic()` savepoints with guaranteed rollback. | ✅ Complete |
| **DB Query Interceptor** | [`dqs/adapters/drf/query_interceptor.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/adapters/drf/query_interceptor.py) | Hooks into database drivers (`execute_wrapper`) and inspects Python call stacks to pinpoint originating lines of code. | ✅ Complete |
| **Unified `Target` Model** | [`dqs/core/targets.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/core/targets.py) | Represents HTTP endpoints, signals, and background tasks under one unified data model. | ✅ Complete |
| **Static Code Advisor** | [`dqs/core/static_advisor.py`](file:///c:/Users/mprof/OneDrive/Desktop/django-profiler/dqs/core/static_advisor.py) | Performs pure AST scans to flag ORM calls inside loops and blocking synchronous I/O. | ✅ Complete |
| **Mock Data Generator** | `dqs/adapters/drf/mock_generator.py` | Auto-populates test rows using `model_bakery` for path parameter resolution (`/books/<int:pk>/`). | 🟡 In Progress |
| **MCP Agent Server** | `dqs/mcp/server.py` | Exposes profiling capabilities as AI-callable tools for Cursor & Claude. | 🔲 Planned |

---

## 📚 Documentation Sitemap & File Reference

Whether you're a developer integrating Da Profiler or an open-source contributor looking to hack on the codebase, check out these guides:

- 🚀 [**Quickstart Guide**](./quickstart.md): Get up and running in 5 minutes.
- 💡 [**How It Works (ELI5)**](./how-it-works.md): Simple explanations of Sandboxing, AST Fingerprinting, and Interceptors.
- 🛠️ [**Developer Onboarding & File Reference Guide**](./developer-onboarding.md): Complete file-by-file reference walkthrough of every module in the repository.
- ❓ [**Frequently Asked Questions (FAQ)**](./faq.md): Common questions, comparisons with Silk/Debug Toolbar, and safety guarantees.
- 🏗️ [**System Architecture Blueprint**](../architecture.md): In-depth technical architecture document and sequence diagrams.
