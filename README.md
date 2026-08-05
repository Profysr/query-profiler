<p align="center">
  <img src="imgs/logo.webp" alt="Da Profiler Logo" width="120">
</p>

[![PyPI version](https://img.shields.io/badge/pypi-v0.3.0-blue.svg)](https://pypi.org/project/da-profiler/)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![Django Support](https://img.shields.io/badge/django-4.2%20%7C%205.0%20%7C%205.1%20%7C%205.2-green)](https://www.djangoproject.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

![Da Profiler Banner](imgs/da-profile-social-banner.png)

> **The Agentic ORM Profiler & Performance Orchestrator for Django.**

`Da Profiler` (package `dqs`) discovers your Django project's endpoints automatically, executes them safely in isolated, self-rolling-back transaction savepoints, intercepts queries at the DB-driver boundary, and detects N+1 queries using AST-based SQL fingerprinting — then hands the result to an AI coding agent (or a human) as a prescriptive, copy-pasteable ORM fix.

---

## ⚡ Quick Navigation

- [Key Features](#-key-features)
- [Why Da Profiler?](#-why-da-profiler)
- [Feature Comparison](#-feature-comparison)
- [Architecture & Design](#-architecture--design)
- [How It Works](#-how-it-works)
- [Dynamic Route & Mock Data Engine](#-dynamic-route--mock-data-engine)
- [AI Agent Integration (MCP)](#-ai-agent-integration-mcp)
- [Installation & Quickstart](#-installation--quickstart)
- [Running Tests](#-running-tests)
- [Project Documentation](#-project-documentation)
- [Contributing & License](#-contributing--license)

---

## ✨ Key Features

- 🛡️ **Zero-Trace Transaction Sandbox**: Runs profile targets inside `transaction.atomic()` savepoints, automatically rolling back mutations post-execution. Real DB state is never modified.
- 🧬 **AST-Based SQL Fingerprinting**: Powered by `sqlglot`. Strips numeric/string literals, normalizes dynamic `IN (...)` parameter lists, and canonicalizes table aliases to eliminate false positives.
- 🎯 **Target Discovery Engine**: Auto-discovers Django views (FBV, CBV, DRF ViewSets), signal receivers (`post_save`, `pre_save`, etc.), Celery tasks, and Channels ASGI consumers.
- 🔮 **Dynamic Parameter & Payload Resolution**: Resolves parameterized routes (`/books/<int:pk>/`) and automatically infers DRF serializer mock payloads for `POST`, `PUT`, and `PATCH` requests.
- 💡 **Prescriptive Fix Suggestions**: Pinpoints N+1 origins to precise user code lines and outputs exact `.select_related()` or `.prefetch_related()` remediation logic.
- 🤖 **Agent-First (MCP Ready)**: Exposes tool hooks (`list_django_routes`, `profile_endpoint`, `seed_mock_data`) for Cursor, Claude Code, and Windsurf to profile, fix, and verify performance headlessly.
- 🧱 **Decoupled Engine Design**: Strict separation between framework-agnostic analysis (`dqs/core/`) and Django/DRF adapters (`dqs/adapters/drf/`).

---

## 💡 Why Da Profiler?

Traditional profilers (e.g. Django Debug Toolbar, Django Silk) are **reactive and human-dependent**:
1. You must manually click around a web browser to populate query logs.
2. Logged queries pollute development database tables or log outputs.
3. You get raw SQL outputs rather than structured, actionable ORM fixes.

`Da Profiler` flips this workflow:
- **Proactive & Headless**: Scans URL pattern trees without manual browsing.
- **Zero-Footprint DB Execution**: Transactions roll back immediately.
- **Prescriptive ORM Remediation**: Converts raw AST query structures into exact Django queryset code fixes.
- **Agentic Loop**: Designed for automated dev agents to inspect, refactor, and re-verify performance fixes end-to-end.

---

## 📊 Feature Comparison

| Feature | Django Debug Toolbar | Django Silk | Da Profiler (`dqs`) |
|---|---|---|---|
| **Discovery** | Manual page rendering | Passive traffic logging | **Active URL & signal discovery tree** |
| **DB Footprint** | None | High (persists log rows to DB) | **Zero (100% savepoint rollback)** |
| **N+1 Detection** | Visual inspect per request | Manual SQL review | **Automated AST fingerprinting (`sqlglot`)** |
| **Fix Generation** | None | None | **Prescriptive ORM (`.select_related()`)** |
| **Param Resolution**| Manual input | Manual traffic | **Automatic mock seeding & URL reversal** |
| **CI / AI Workflow**| Not supported | Not supported | **Native MCP server for AI IDE agents** |

---

## 🏗️ Architecture & Design

Da Profiler enforces a clean architectural separation:

```
dqs/
├── core/                  # Pure Python engine — zero Django dependencies
│   ├── analyzer.py        # AST SQL fingerprinting & N+1 detection
│   ├── static_advisor.py  # Pure AST code scanner (loops & blocking I/O)
│   └── targets.py         # Framework-agnostic Target model
└── adapters/
    └── drf/               # Django & DRF integration adapter
        ├── discovery.py   # Route, signal, task, and consumer discovery
        ├── runner.py      # Isolated savepoint execution runner
        ├── converters.py  # Dynamic path parameter resolver
        ├── body_inferrer.py# Serializer request payload inferrer
        └── mock_generator.py # Model Bakery mock data engine
```

> 📖 For full system diagrams and execution sequence specifications, check out [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## 🔍 How It Works

### Step-by-Step N+1 Identification

#### 1. Unoptimized View Code
```python
# sample_app/views.py
from django.http import JsonResponse
from .models import Book

def list_books(request):
    books = Book.objects.all()  # Initial query
    data = [
        {"title": book.title, "author": book.author.name}  # N+1 queries in loop
        for book in books
    ]
    return JsonResponse(data, safe=False)
```

#### 2. Captured SQL Execution
```sql
SELECT "id", "title", "author_id" FROM "sample_app_book";
SELECT "id", "name" FROM "sample_app_author" WHERE "id" = 10;
SELECT "id", "name" FROM "sample_app_author" WHERE "id" = 25;
SELECT "id", "name" FROM "sample_app_author" WHERE "id" = 42;
```

#### 3. AST Normalization (`dqs.core.analyzer`)
Queries parse into AST representations and collapse to a single fingerprint:
```sql
SELECT "id", "name" FROM "sample_app_author" WHERE "id" = ?
```

#### 4. Prescriptive Report Output
```json
{
  "fingerprint": "SELECT \"id\", \"name\" FROM \"sample_app_author\" WHERE \"id\" = ?",
  "count": 3,
  "source_location": "sample_app/views.py:7",
  "suggestion": "Add .select_related('author') to your QuerySet."
}
```

---

## 🛠️ Dynamic Route & Mock Data Engine

For routes like `/books/<int:pk>/` or `/authors/<uuid:id>/`:

```
1. Introspect Path Converters  ---> 2. Resolve Model & Seed Mock  ---> 3. Reverse Executable URL
   (int, uuid, slug, str, path)     (via model_bakery & cache)           (/books/42/)
```

`POST` / `PUT` request bodies are dynamically built by `dqs.adapters.drf.body_inferrer` by inspecting DRF serializers (`serializer_class`) or Django forms.

---

## 🤖 AI Agent Integration (MCP)

Da Profiler provides a Model Context Protocol (MCP) server for Cursor, Windsurf, and Claude Code:

```
+------------------+         list_django_routes()         +------------------+
|                  | -----------------------------------> |                  |
|   AI IDE Agent   |        profile_endpoint(target)      |   Da Profiler    |
| (Cursor / Claude)| -----------------------------------> |    MCP Server    |
|                  | <----------------------------------- |                  |
+------------------+     Enriched Findings & ORM Fix      +------------------+
```

---

## 🚀 Installation & Quickstart

### Installation

```bash
pip install da-profiler[django]
```

Add `dqs.adapters.drf` to your `INSTALLED_APPS` (development environment only):

```python
# settings.py
if DEBUG:
    INSTALLED_APPS += ["dqs.adapters.drf"]
```

---

### Development Setup (Docker)

```bash
# 1. Clone repository
git clone https://github.com/Profysr/query-profiler.git
cd query-profiler

# 2. Configure environment
cp .env.example .env

# 3. Build containers and start Postgres
docker compose build
docker compose up -d db

# 4. Start stack and run migrations
docker compose up -d
docker compose exec web python manage.py migrate
```

---

## 🧪 Running Tests

Run the test suite inside the Docker container using `pytest`:

```bash
# Run all tests
docker compose run --rm web pytest

# Run pure core tests (framework-agnostic, zero DB)
docker compose run --rm web pytest -m core

# Run Django adapter tests
docker compose run --rm web pytest -m django
```

---

## 📚 Project Documentation

- 📄 [`ARCHITECTURE.md`](./ARCHITECTURE.md) — System design, sequence flows, and component breakdown.
- 📋 [`CHANGELOG.md`](./CHANGELOG.md) — Detailed version history, releases, and architectural decisions.
- 🗺️ [`ROADMAP.md`](./ROADMAP.md) — Development milestones, planned adapters, and feature timelines.
- 🤝 [`CONTRIBUTING.md`](./CONTRIBUTING.md) — Contribution guidelines, dev setup, and commit standards.
- 🔒 [`SECURITY.md`](./SECURITY.md) — Security policy and vulnerability reporting.
- 📜 [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) — Community guidelines.

---

## 📄 Contributing & License

Contributions are welcome! Please review [`CONTRIBUTING.md`](./CONTRIBUTING.md) before opening a pull request.

Distributed under the **MIT License**. See [`LICENSE`](./LICENSE) for details.
 