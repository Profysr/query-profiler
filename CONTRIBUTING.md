# Contributing to Query Sandbox (DQS)

First off, thank you for considering contributing to DQS — it means a lot. This project only gets better with more hands on it, and we'd love yours.

This guide covers everything you need to go from "I want to help" to your first merged PR.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Ways to Contribute](#ways-to-contribute)
- [Development Setup](#development-setup)
- [Branching & Commit Conventions](#branching--commit-conventions)
- [Coding Standards](#coding-standards)
- [Documentation Map](#documentation-map)
- [Documentation-Only Contributions](#documentation-only-contributions)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)
- [Getting Help](#getting-help)

## Code of Conduct

This project follows our [Code of Conduct](./CODE_OF_CONDUCT.md). By participating, you agree to uphold it. Be kind, be respectful, and assume good intent.

## Ways to Contribute

You don't have to write code to contribute meaningfully:

- 🐛 **Report bugs** — see [Reporting Bugs](#reporting-bugs)
- 💡 **Suggest features** — see [Suggesting Features](#suggesting-features)
- 📝 **Improve documentation** — typos, unclear setup steps, missing examples
- 🧪 **Write tests** — especially fingerprinting edge cases (subqueries, nested boolean logic) — always want better coverage here
- 🔧 **Fix issues** — check issues labeled [`good first issue`](https://github.com/Profysr/django-query-sandbox/labels/good%20first%20issue) or [`help wanted`](https://github.com/Profysr/django-query-sandbox/labels/help%20wanted)
- 🧩 **Build a new framework adapter** — see the note in [Coding Standards](#coding-standards) before starting one; open an issue first so we can align on scope

## Development Setup

1. **Fork** the repo (click **Fork** at the top of the GitHub page)

2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/django-query-sandbox.git
   cd django-query-sandbox
   ```

3. **Add the original repo as upstream** (so you can pull in future updates):
   ```bash
   git remote add upstream https://github.com/Profysr/django-query-sandbox.git
   ```

4. **Set up the project** — follow the [Quickstart](./README.md#quickstart-development-environment) section in the README. Docker is the *only* supported path — no local Python install is required or expected.

5. **Verify everything works** before making changes:
   ```bash
   docker compose build
   docker compose up -d
   docker compose exec web python manage.py migrate
   ```
   Confirm the dashboard loads at `http://localhost:8000/dqs/`.

## Branching & Commit Conventions

**Branch naming:**
```
feature/short-description     # new features
fix/short-description         # bug fixes
docs/short-description        # documentation only
refactor/short-description    # code changes with no behavior change
```
Example: `feature/subquery-fingerprinting`, `fix/in-clause-empty-list`

**Commit messages** — we loosely follow [Conventional Commits](https://www.conventionalcommits.org/):
```
feat: add subquery normalization to fingerprint()
fix: handle empty IN () clause without crashing
docs: clarify relationships dict key contract
refactor: split introspector route parsing into helper
test: add coverage for OR-clause fingerprint skip
```

Keep commits focused — one logical change per commit is easier to review than one giant commit touching ten files.

## Coding Standards

**Core (`dqs/core/`) — the framework-agnostic engine:**
- **Must never import Django** (or any framework/ORM). If `dqs/core/analyzer.py` or `dqs/core/dashboard/` needs something Django-specific, that's a sign the code belongs in an adapter instead — see [Architecture](./README.md#architecture) in the README for the full reasoning.
- Functions here should operate on plain `dict`s/lists, not framework objects, so the same code can eventually serve a non-Django adapter untouched.
- Follow [PEP 8](https://peps.python.org/pep-0008/); lint with `ruff`:
  ```bash
  docker compose exec web ruff check dqs/
  ```

**Adapters (`dqs/adapters/<framework>/`):**
- Framework-specific code lives here, and only here. Django imports belong in `dqs/adapters/django/`, nowhere else.
- If you're building a *new* adapter (e.g. FastAPI/SQLAlchemy), open an issue first — this is also the point where `BaseIntrospector`/`BaseSandboxRunner` abstract contracts get formalized based on what the second real implementation needs, not guessed at in advance. See `CHANGELOG.md` for why this was deliberately deferred.

**Tests:**
- New logic in `dqs/core/` → add/update the matching test in `tests/test_analyzer.py`. These tests must stay Django-free — if one suddenly needs Django to pass, something has leaked across the core/adapter boundary and should be flagged in review, not merged.
- New logic in `dqs/adapters/django/` → add/update `tests/test_introspector.py` or `tests/test_runner.py` as appropriate.
- Run tests locally:
  ```bash
  docker compose run --rm web pytest
  ```

**General:**
- No commented-out dead code in PRs.
- No secrets, API keys, or `.env` files committed — double check with `git diff` before pushing.
- If your fingerprinting change affects a case we've explicitly called out as punted (subqueries, `OR`-clause reordering — see `CHANGELOG.md`), say so in the PR description rather than silently changing the scope decision.

## Documentation Map

If your change affects any of the below, update the matching file in the same PR — don't leave it for later.

| If your change touches... | Update this file |
|---|---|
| A new architectural decision, a tradeoff, or *why* something is built a certain way | [`CHANGELOG.md`](./CHANGELOG.md) |
| What's built vs. planned, which version a feature belongs to | [`ROADMAP.md`](./ROADMAP.md) |
| Setup steps, quickstart, architecture overview, feature list | [`README.md`](./README.md) |
| Fingerprinting logic, normalization steps, N+1 detection rules | Docstrings in [`dqs/core/analyzer.py`](./dqs/core/analyzer.py) — keep them in sync with `CHANGELOG.md` §7 rather than duplicating the reasoning in two places |

**Rule of thumb:** if a reviewer would need to ask "wait, why does it work this way?" after reading your diff, the answer belongs in `CHANGELOG.md`, not just in your PR description.

## Documentation-Only Contributions

Docs improvements are just as valuable as code — typo fixes, clarifying a confusing setup step, a missing example in the README's fingerprinting walkthrough. These follow the same PR process but skip the testing requirements above.

## Submitting a Pull Request

1. Create your branch from the latest `main`:
   ```bash
   git checkout main
   git pull upstream main
   git checkout -b feature/your-feature-name
   ```

2. Make your changes, commit them, and push to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

3. Open a Pull Request against `Profysr/django-query-sandbox:main`. Describe **what** changed and **why**, and link any related issue (e.g. `Closes #12`).

4. Ensure CI passes (lint + tests run automatically on every PR).

5. A maintainer will review your PR. We may ask for changes — this is normal and not a rejection. Once approved, we'll merge it.

**PR checklist before requesting review:**
- [ ] Code respects the `core`/`adapters` boundary (no Django imports in `dqs/core/`)
- [ ] Tests added/updated, and `dqs/core/` tests remain Django-free
- [ ] `ruff check dqs/` passes with no errors
- [ ] `CHANGELOG.md` and/or `ROADMAP.md` updated if this PR makes or changes an architectural decision
- [ ] PR description explains the change and links any related issue

## Reporting Bugs

Before opening a new issue, please search [existing issues](https://github.com/Profysr/django-query-sandbox/issues) to avoid duplicates.

When filing a bug report, include:
- Clear steps to reproduce (ideally the exact SQL or Django queryset that triggered it, if fingerprinting-related)
- Expected vs. actual behavior
- Your environment (Docker version, Django/DRF version if relevant)

## Suggesting Features

Open a feature request describing:
- The problem you're trying to solve (not just the solution)
- Whether it fits inside `dqs/core/` (framework-agnostic) or belongs in an adapter
- Any alternatives you've considered

For larger features — especially a new framework adapter — it's worth opening an issue to discuss the approach *before* investing time in a full implementation, since the adapter contract isn't finalized yet and early discussion avoids a rewrite.

## Getting Help

- Check the [README](./README.md), [`ROADMAP.md`](./ROADMAP.md), and [`CHANGELOG.md`](./CHANGELOG.md) first — most "why does this work this way" questions are already answered there
- Search [existing issues](https://github.com/Profysr/django-query-sandbox/issues) and Discussions
- Still stuck? Open a new Discussion — happy to help you get unblocked

---

Thanks again for contributing — every PR, issue, and suggestion helps make DQS better for developers who need it. 🙌