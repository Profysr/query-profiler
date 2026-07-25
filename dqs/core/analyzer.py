import sqlglot
import sqlglot.expressions as exp
from collections import defaultdict

# ==============================
# Helper Functions
# ==============================
def _contains_or(condition: exp.Expression) -> bool:
    """True if an OR appears anywhere in this condition subtree."""
    return any(True for _ in condition.find_all(exp.Or))


def _sorted_and_chain(condition: exp.Expression) -> exp.Expression:
    """
    Flattens a pure AND chain into its individual conditions, sorts them by
    their normalized SQL text for a stable order, and rebuilds the chain.
    Only called after confirming there's no OR in the tree — safe to reorder.
    """
    if isinstance(condition, exp.And):
        parts = list(condition.flatten())
    else:
        parts = [condition]

    parts_sorted = sorted(parts, key=lambda c: c.sql())

    rebuilt = parts_sorted[0]
    for part in parts_sorted[1:]:
        rebuilt = exp.and_(rebuilt, part)
    return rebuilt


# ==============================
# Main Defs
# ==============================
def fingerprint(raw_sql: str) -> str:
    """
    Parses raw SQL using sqlglot and normalizes syntactic variations so that
    structurally-identical queries collapse to the same fingerprint string.

    Steps (see CHANGELOG.md #7 for the reasoning behind each):
    1. Replaces individual literals (numbers, strings) with '?'
    2. Collapses `IN (...)` lists to a single '?' placeholder, regardless of length
    3. Canonicalizes table aliases to T0, T1, etc. across definitions AND column
       references (so joins with different alias names still match)
    4. Sorts top-level AND-chained WHERE conditions alphabetically — ONLY when
       the condition tree contains no OR anywhere. Reordering an OR-mixed
       expression isn't generically safe (changes precedence/grouping), so we
       skip normalization entirely rather than risk a wrong match. This is a
       deliberate scope line, not an oversight — see CHANGELOG.md "punted" notes.

    NOTE: this only achieves "100% accurate" grouping for the query shapes
    Django's ORM actually generates for a repeated queryset pattern in a loop.
    It does not (and can't, in general) prove semantic equivalence between
    arbitrary SQL — see CHANGELOG.md #7 for why that's a hard ceiling for any
    fingerprinting approach, not a gap specific to this implementation.
    """
    try:
        parsed = sqlglot.parse_one(raw_sql)
    except Exception:
        # Fallback to trimmed string if SQL parsing fails. This deliberately
        # swallows parser errors rather than crashing the whole profiling run
        # a query we can't fingerprint just won't get grouped with anything, which is a safe failure mode (undercounts N+1, never overcounts it).
        return raw_sql.strip()

    if parsed is None:
        # Defensive: parse_one can return None on some malformed input without raising. Guard here so the steps below don't blow up on .find_all(None).
        return raw_sql.strip()

    # 1. Strip individual literals (numbers, quoted strings)
    for node in parsed.find_all(exp.Literal):
        node.replace(exp.Literal.string("?"))

    # 2. Collapse IN (...) lists to a single placeholder regardless of length.
    #    Without this, `IN (1,2)` and `IN (1,2,3,4,5)` would fingerprint differently even though they're the same query shape.
    for node in parsed.find_all(exp.In):
        node.set("expressions", [exp.Literal.string("?")])

    # 3a. Canonicalize table alias definitions (AS T0, AS T1...)
    alias_map = {}
    for node in parsed.find_all(exp.TableAlias):
        original_alias = node.this.name
        if original_alias not in alias_map:
            alias_map[original_alias] = f"T{len(alias_map)}"
        node.this.set("this", alias_map[original_alias])

    # 3b. Update all column table qualifiers (T5.id -> T0.id) to match mapped aliases. Without this step, the table alias definition would be renamed but every column reference using the old table would be left stale. This is the part it's easy to forget and get wrong.
    for col in parsed.find_all(exp.Column):
        table_identifier = col.args.get("table")
        if table_identifier and table_identifier.name in alias_map:
            table_identifier.set("this", alias_map[table_identifier.name])

    # 4. Sort top-level AND-chained WHERE conditions alphabetically, so `WHERE x = ? AND y = ?` and `WHERE y = ? AND x = ?` fingerprint identically. Skipped entirely if OR appears anywhere in the condition.
    where = parsed.find(exp.Where)
    if where is not None and not _contains_or(where.this):
        where.set("this", _sorted_and_chain(where.this))

    return parsed.sql()


def suggest_fix(fp: str, relationships: dict = None) -> str:
    """
    Generates template-based ORM optimization suggestions based on known
    table relationship metadata.

    `relationships` MUST be keyed by the real database table name (e.g.
    Django's `app_label_modelname` convention, like "sample_app_author"),
    not the bare model name ("author") — this function matches against
    `exp.Table` nodes extracted from the fingerprinted SQL, which contain
    the actual table name Django generated in the query, not the model name.
    Building this dict correctly is the Introspector's responsibility.

        {"sample_app_author": {"relation": "author", "type": "foreign_key"}}
    """
    if not relationships:
        return "Consider optimizing QuerySets using select_related() or prefetch_related()."

    try:
        parsed = sqlglot.parse_one(fp)
        tables = [table.name.lower().strip('"') for table in parsed.find_all(exp.Table)]
    except Exception:
        tables = []

    for table in tables:
        if table in relationships:
            rel_info = relationships[table]
            rel_name = rel_info.get("relation")
            rel_type = rel_info.get("type", "foreign_key")

            if rel_type in ("foreign_key", "one_to_one"):
                return f"Add `.select_related('{rel_name}')` to your QuerySet."
            elif rel_type in ("many_to_many", "reverse_foreign_key"):
                return f"Add `.prefetch_related('{rel_name}')` to your QuerySet."

    return "Consider optimizing QuerySets using select_related() or prefetch_related()."


def detect_n_plus_one(
    queries: list[dict],
    threshold: int = 3,
    relationships: dict = None
) -> list[dict]:
    """
    Groups query logs by fingerprint and flags any SELECT query group
    executing >= threshold times, attaching fix suggestions.

    threshold defaults to 3, two repeated queries is common and often
    fine (e.g. a page genuinely doing two unrelated lookups); three-plus of
    the same shape is a much lower-noise signal for a junior dev's first
    impression of the tool. See CHANGELOG.md #8.
    """
    groups = defaultdict(list)

    for q in queries:
        sql = q.get("sql", "")
        fp = fingerprint(sql) # Calculating the fingerprint for each query
        groups[fp].append(q)

    flags = []
    for fp, group in groups.items():
        # Only flag SELECTs — INSERT/UPDATE/DELETE repetition isn't the N+1 pattern this tool targets, and grouping them could produce noisy, confusing suggestions (select_related doesn't apply to a write).
        if len(group) >= threshold and fp.strip().upper().startswith("SELECT"):
            flags.append({
                "fingerprint": fp,
                "count": len(group),
                "suggestion": suggest_fix(fp, relationships),
                "queries": group,
            })

    return flags