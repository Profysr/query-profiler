## Description

<!-- Briefly describe what this PR does and why. What problem does it solve? -->



## Related Issue

<!-- Link the issue this PR addresses, if any. Use "Closes #123" to auto-close it on merge. -->

Closes #

## Type of Change

<!-- Check all that apply -->

- [ ] 🐛 Bug fix (non-breaking change that fixes an issue)
- [ ] ✨ New feature (non-breaking change that adds functionality)
- [ ] 💥 Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] 📝 Documentation update
- [ ] ♻️ Refactor (no functional changes)
- [ ] 🔍 Fingerprinting / N+1 detection logic change
- [ ] 🧩 New or modified framework adapter (Django, or a new one)
- [ ] 🧪 Test coverage
- [ ] 🔧 Chore / tooling / CI

## What Changed

<!-- List the key changes. Bullet points are fine. -->

-
-
-

## Which layer does this touch?

<!-- Check all that apply. If you checked both core and adapters, double check dqs/core/ still has zero Django imports. -->

- [ ] `dqs/core/` (framework-agnostic — analyzer, dashboard)
- [ ] `dqs/adapters/drf/` (Django-specific)
- [ ] `demo_project/` (dev/test scaffolding only, not shipped)
- [ ] Docs only (`README.md`, `ROADMAP.md`, `CHANGELOG.md`)

## Fingerprinting Impact

<!-- Only fill this out if your change touches dqs/core/analyzer.py. Delete this section otherwise. -->

- [ ] This changes how queries are fingerprinted or grouped
- [ ] I checked `CHANGELOG.md` #7 to confirm this isn't reversing a deliberate scope cut (subqueries, OR-clause reordering, etc.) — if it is, I've explained why below
- [ ] I tested this against the AND-sort, IN-collapse, and alias-canonicalization cases already covered in `tests/test_analyzer.py` to confirm no regressions

## Screenshots / Recordings

<!-- Required for any Dashboard UI change. Before/after screenshots help reviewers a lot. Delete this section if not applicable. -->



## How Has This Been Tested?

<!-- Describe how you tested your changes. -->

- [ ] Ran `pytest` (`docker compose run --rm web pytest`)
- [ ] Ran `ruff check dqs/`
- [ ] Manually tested against `demo_project`'s sample endpoints in Docker (`docker compose up`)
- [ ] Confirmed `tests/test_analyzer.py` still passes without requiring Django (core/adapter boundary intact)

**Test steps:**
1.
2.
3.

## Checklist

- [ ] My code follows the project's coding standards (see [CONTRIBUTING.md](../CONTRIBUTING.md))
- [ ] I have performed a self-review of my own code
- [ ] I have commented my code where necessary, particularly in hard-to-understand areas (e.g. the AST normalization steps in `analyzer.py`)
- [ ] `dqs/core/` contains no Django (or other framework) imports
- [ ] I have made corresponding changes to the documentation — see the [Documentation Map](../CONTRIBUTING.md#documentation-map) to find the right file for your change
- [ ] If this is an architectural decision or a tradeoff, I've added a note to `CHANGELOG.md`
- [ ] My changes generate no new warnings or linter errors
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] New and existing unit tests pass locally with my changes
- [ ] I have checked that no secrets, API keys, or `.env` files are included in this PR
- [ ] Any dependent changes have been merged and published

## Additional Notes

<!-- Anything else reviewers should know — trade-offs made, follow-up work planned, areas you'd like specific feedback on. -->