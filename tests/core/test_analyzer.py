import pytest
from dqs.core.analyzer import fingerprint, detect_n_plus_one, suggest_fix


def test_fingerprint_strips_literals():
    sql1 = "SELECT * FROM author WHERE id = 10;"
    sql2 = "SELECT * FROM author WHERE id = 999;"
    assert fingerprint(sql1) == fingerprint(sql2)


def test_fingerprint_collapses_in_clauses():
    sql1 = "SELECT * FROM book WHERE id IN (1, 2, 3);"
    sql2 = "SELECT * FROM book WHERE id IN (10, 20, 30, 40, 50);"
    assert fingerprint(sql1) == fingerprint(sql2)


def test_fingerprint_canonicalizes_aliases():
    sql1 = 'SELECT T0."id" FROM "publisher" T0 WHERE T0."name" = \'OReilly\''
    sql2 = 'SELECT T5."id" FROM "publisher" T5 WHERE T5."name" = \'Manning\''
    assert fingerprint(sql1) == fingerprint(sql2)


def test_suggest_fix_select_related():
    fp = 'SELECT T0."id" FROM "author" T0 WHERE T0."id" = ?'
    relationships = {"author": {"relation": "author", "type": "foreign_key"}}
    
    suggestion = suggest_fix(fp, relationships)
    assert suggestion == "Add `.select_related('author')` to your QuerySet."


def test_suggest_fix_prefetch_related():
    fp = 'SELECT T0."id" FROM "books" T0 WHERE T0."author_id" = ?'
    relationships = {"books": {"relation": "books", "type": "reverse_foreign_key"}}
    
    suggestion = suggest_fix(fp, relationships)
    assert suggestion == "Add `.prefetch_related('books')` to your QuerySet."


def test_detect_n_plus_one_flags_threshold():
    queries = [
        {"sql": 'SELECT * FROM "author" WHERE id = 1', "time": "0.001"},
        {"sql": 'SELECT * FROM "author" WHERE id = 2', "time": "0.001"},
        {"sql": 'SELECT * FROM "author" WHERE id = 3', "time": "0.001"},
    ]
    relationships = {"author": {"relation": "author", "type": "foreign_key"}}

    flags = detect_n_plus_one(queries, threshold=3, relationships=relationships)
    assert len(flags) == 1
    assert flags[0]["count"] == 3
    assert "select_related" in flags[0]["suggestion"]