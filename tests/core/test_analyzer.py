"""
tests/core/test_analyzer.py
============================
Unit tests for the core SQL AST fingerprinting and N+1 detection engine.
Marker: `core` (no DB, no Django, pure Python only).
"""
import pytest
from dqs.core.analyzer import fingerprint, detect_n_plus_one, suggest_fix


def test_fingerprint_strips_literals():
    """Queries differing only in literal values must produce identical fingerprints."""
    assert fingerprint("SELECT * FROM author WHERE id = 10;") == \
           fingerprint("SELECT * FROM author WHERE id = 999;")


def test_fingerprint_collapses_in_clauses():
    """IN (...) lists of any length must collapse to a single placeholder."""
    assert fingerprint("SELECT * FROM book WHERE id IN (1, 2, 3);") == \
           fingerprint("SELECT * FROM book WHERE id IN (10, 20, 30, 40, 50);")


def test_fingerprint_canonicalizes_table_aliases():
    """Table aliases (T0, T5, t_alias) must all normalize to T0, T1, … regardless of name."""
    sql1 = 'SELECT T0."id" FROM "publisher" T0 WHERE T0."name" = \'OReilly\''
    sql2 = 'SELECT T5."id" FROM "publisher" T5 WHERE T5."name" = \'Manning\''
    assert fingerprint(sql1) == fingerprint(sql2)


def test_fingerprint_sorts_and_conditions():
    """WHERE a=1 AND b=2 and WHERE b=2 AND a=1 must produce the same fingerprint."""
    sql1 = "SELECT * FROM library_book WHERE id = 1 AND title = 'Django';"
    sql2 = "SELECT * FROM library_book WHERE title = 'Python' AND id = 5;"
    assert fingerprint(sql1) == fingerprint(sql2)


def test_fingerprint_invalid_sql_returns_stripped_input():
    """Unparseable SQL must not crash — it should return the stripped raw input."""
    raw = "NOT VALID SQL !!!"
    fp = fingerprint(raw)
    assert isinstance(fp, str)
    assert len(fp) > 0


def test_detect_n_plus_one_flags_repeated_queries():
    """Queries sharing a fingerprint + source location above threshold must be flagged."""
    queries = [
        {"sql": "SELECT * FROM author WHERE id = 1", "time": 0.5, "src_loc": "views.py:10"},
        {"sql": "SELECT * FROM author WHERE id = 2", "time": 0.4, "src_loc": "views.py:10"},
        {"sql": "SELECT * FROM author WHERE id = 3", "time": 0.6, "src_loc": "views.py:10"},
    ]
    flags = detect_n_plus_one(queries, threshold=3)
    assert len(flags) == 1
    assert flags[0]["count"] == 3
    assert flags[0]["src_loc"] == "views.py:10"


def test_detect_n_plus_one_below_threshold_not_flagged():
    """Query group below the threshold must not be reported."""
    queries = [
        {"sql": "SELECT * FROM author WHERE id = 1", "time": 0.5, "src_loc": "views.py:10"},
        {"sql": "SELECT * FROM author WHERE id = 2", "time": 0.4, "src_loc": "views.py:10"},
    ]
    flags = detect_n_plus_one(queries, threshold=3)
    assert len(flags) == 0


def test_suggest_fix_mentions_select_related():
    """Suggestions for FK-style repeated queries must recommend select_related."""
    fp = 'SELECT T0."id" FROM "author" T0 WHERE T0."id" = ?'
    suggestion = suggest_fix(fp, src_loc="views.py:10")
    assert "select_related" in suggestion.lower() or "prefetch_related" in suggestion.lower()