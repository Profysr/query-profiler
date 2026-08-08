# 🚀 Quickstart Guide (ELI5)

Welcome to **Da Profiler**! This guide will help you install and run your very first isolated query profiling test in less than 5 minutes.

---

## 🧒 What are we trying to do?

Imagine you want to test how fast your web app gets data from the database, but you don't want to mess up your real database or click 100 buttons on your website.

With Da Profiler:
1. You install the package.
2. Da Profiler finds your web pages (endpoints).
3. It pretends to visit them in a "magic bubble" (isolated sandbox).
4. It tells you if your code is making too many database requests!

---

## 📋 Step 1: Install Da Profiler

Add `da-profiler` to your Django project's dependencies:

```bash
pip install da-profiler[django]
```

*(Or if working from the source repository, `pip install -e .`)*

---

## ⚙️ Step 2: Register in `settings.py`

Open your Django project's `settings.py` file and add `dqs.adapters.drf` to `INSTALLED_APPS`:

```python
# settings.py

INSTALLED_APPS = [
    # ... your existing Django apps ...
    'dqs.adapters.drf',  # Registers Da Profiler Django adapter
]

DATABASE_ROUTERS = [
    'dqs.adapters.drf.router.DQSRouter',  # Registers Da Profiler database router
]
```

> [!IMPORTANT]
> **Safety Guard**: Da Profiler requires `DEBUG = True` in your settings to protect production environments from running sandbox simulations.
>
> **Shadow Database Setup**: Configure a `dqs_shadow` entry in `DATABASES` matching your engine and run migrations:
> ```bash
> python manage.py migrate --database=dqs_shadow
> ```

---

## 🧪 Step 3: Run Your First Isolated Profile

You can run Da Profiler directly from Python code or a management script:

```python
from dqs.adapters.drf.execution.runner import DjangoSandboxRunner
from dqs.core.analyzer import detect_n_plus_one

# 1. Initialize the sandbox runner
runner = DjangoSandboxRunner()

# 2. Execute an endpoint in isolated savepoint sandbox
# (This simulates GET /api/books/ without saving anything to the DB!)
result = runner.execute_isolated(
    url_name_or_path="/api/books/",
    method="GET"
)

print(f"Status Code: {result.status_code}")
print(f"Total Database Queries Fired: {result.metrics['total_queries']}")

# 3. Analyze for N+1 bottlenecks
for n1 in result.analysis:
    print("\n⚠️ Bottleneck Detected!")
    print(f"File & Line: {n1['src_loc']}")
    print(f"Repeated Query Count: {n1['count']}")
    print(f"Suggested Fix: {n1['suggestion']}")
```

---

## 🎯 What Happens Under the Hood?

When you run `execute_isolated()`:
1. **Magic Savepoint**: Django opens a `transaction.atomic()` savepoint.
2. **Query Interception**: Every SQL query is recorded along with the exact file name and line number in your code.
3. **Automatic Rollback**: The savepoint is rolled back immediately when execution finishes. **Zero database clutter!**

---

## ⏩ Next Steps

- Want to understand how Da Profiler works under the hood? Check out [How It Works (ELI5)](./how-it-works.md).
- Interested in contributing? Read [Developer Onboarding](./developer-onboarding.md).