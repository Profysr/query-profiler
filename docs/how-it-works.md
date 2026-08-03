# 💡 How It Works

This document breaks down the core concepts of **Da Profiler** using simple, everyday analogies!

---

## 🏎️ The Problem: The N+1 Query Trap

Imagine you run a library app:
1. You ask the database for 50 books: `SELECT * FROM books;` *(1 query)*
2. For **each** book, you ask the database for the author's name: `SELECT * FROM authors WHERE id = 10;`, `SELECT * FROM authors WHERE id = 12;`, etc. *(50 queries)*

Total: **51 database queries!** This is called an **N+1 Query**. Instead of getting all author names in one big order, your code keeps nagging the database over and over.

---

## 🪄 1. The Magic Sandbox (Safe Rollbacks)

### 👶 Drawing in the Sand
Imagine building a castle in a sandbox. If you don't like it, you just smooth out the sand with your hand, and it's like it never happened!

### 💻 How Da Profiler does it:
When Da Profiler profiles your code (even a `POST` request that creates 100 fake users), it runs inside a database transaction savepoint (`transaction.atomic()`). 

As soon as the test finishes, Da Profiler immediately triggers a `savepoint_rollback()`. The changes disappear like magic! Your real database is never dirtied or changed.

---

## 🔍 2. AST SQL Fingerprinting

### 👶 Sorting by Shape, Not Color
If you have 50 red bricks and 50 blue bricks, they look slightly different. But if you sort them by shape, they are all the exact same 2x4 rectangular brick!

### 💻 How Da Profiler does it:
Raw SQL queries look different because the IDs change:
- `SELECT * FROM author WHERE id = 1`
- `SELECT * FROM author WHERE id = 42`
- `SELECT * FROM author WHERE id = 99`

Da Profiler uses a tool called `sqlglot` to parse the Abstract Syntax Tree (AST) of the query. It replaces the numbers with a placeholder `?`:
```sql
SELECT * FROM author WHERE id = ?
```

Now, all 50 queries match the **exact same fingerprint**! Da Profiler instantly sees that the same query pattern ran 50 times and flags it as an N+1 bug.

---

## 🕵️ 3. DB Interceptor & Call Stack Fingerprinting

### 👶 The Detective's GPS Tracker
Instead of guessing which room in a giant house a noise came from, the detective places a tiny GPS tracker on every door so they know the exact room instantly!

### 💻 How Da Profiler does it:
Da Profiler hooks directly into Django's database execution wrapper (`connection.execute_wrapper()`). The instant a SQL query fires, Da Profiler inspects Python's active call stack (`inspect.stack()`).

It bypasses framework-internal files (like Django core files) and pinpoints the **exact user file and line number** where the query originated:
```
Potential N+1 detected on table 'authors' at sample_app/views.py:38
```

---

## 🤖 4. Static Code Advisor

### 👶 Spell-Check Before You Spell Out Loud
You don't need to speak a sentence out loud to realize a word is misspelled, your eyes can catch it on paper!

### 💻 How Da Profiler does it:
The `StaticASTAdvisor` scans your Python source files **statically** without running the server or connecting to any database. It looks for risky patterns such as:
- Calling database functions inside `for` loops (`for item in items: Item.objects.get(...)`).
- Slow, blocking network calls (`requests.get(...)` or `time.sleep(...)`) in request handlers.

---

## 📚 Want to learn more?

- Read the full technical architecture in [Architecture Blueprint](../architecture.md).
- Learn how to contribute in [Developer Onboarding](./developer-onboarding.md).
