"""Associating the PMIDs of a PubMed query to a run, PubMed replaced by a fixed search."""

import json
from datetime import date

import pytest

from database.pubmed import associate

IN_VH_RUN = 8626429  # associated to the vh run 1-16 in the fixture
NEW = [990000001, 990000002]


def _new_run(conn, run_type: str = "vh") -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO runs (type, name) VALUES (%s, '99') RETURNING id", (run_type,))
        (run_id,) = cur.fetchone()
    conn.commit()
    return run_id


def _found(*pmids: int):
    return lambda query, start, end: sorted(pmids)


def test_new_pmids_are_associated_as_pending_and_the_window_recorded(conn):
    run_id = _new_run(conn)
    report = associate(
        conn,
        run_id,
        "virus*[tiab]\nAND bind*[tiab]",
        date(2026, 1, 1),
        date(2026, 1, 31),
        search=_found(IN_VH_RUN, *NEW),
    )
    assert "3 PMIDs found" in report
    assert "1 already associated to another vh run, left out" in report
    assert "2 associated as pending, 2 of them new publications" in report
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pmid, state FROM associations WHERE run_id = %s ORDER BY pmid", (run_id,)
        )
        assert cur.fetchall() == [(pmid, "pending") for pmid in NEW]
        cur.execute("SELECT populated, metadata FROM publications WHERE pmid = %s", (NEW[0],))
        assert cur.fetchone() == (False, None)
        cur.execute("SELECT info FROM runs WHERE id = %s", (run_id,))
        assert json.loads(cur.fetchone()[0]) == {
            "query": "virus*[tiab] AND bind*[tiab]",
            "from": "2026-01-01",
            "to": "2026-01-31",
        }


def test_a_pmid_of_a_run_of_the_other_type_is_associated(conn):
    run_id = _new_run(conn, "hh")
    report = associate(
        conn, run_id, "q", date(2026, 1, 1), date(2026, 1, 1), search=_found(IN_VH_RUN)
    )
    assert "1 associated as pending, 0 of them new publications" in report


def test_a_run_that_has_its_query_is_refused(conn):
    run_id = _new_run(conn)
    associate(conn, run_id, "q", date(2026, 1, 1), date(2026, 1, 1), search=_found(*NEW))
    with pytest.raises(ValueError, match="already has its query"):
        associate(conn, run_id, "q", date(2026, 2, 1), date(2026, 2, 1), search=_found(*NEW))


def test_an_unknown_run_is_refused(conn):
    with pytest.raises(ValueError, match="no run with ID"):
        associate(conn, 999999, "q", date(2026, 1, 1), date(2026, 1, 1), search=_found(*NEW))
