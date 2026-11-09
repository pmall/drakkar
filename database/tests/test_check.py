"""Each invariant finds a violation made in the fixture; the fixture itself has no error."""

import pytest

from database.check import INVARIANTS, errors, run_checks

# A live vh row with a mapping on side 1, and a stable ID with several versions; each row is
# found by its stable ID and version.
LIVE_VH = """
    SELECT stable_id, version FROM descriptions_vh
    WHERE deleted_at IS NULL AND json_array_length(mapping1) > 0
    ORDER BY stable_id LIMIT 1
"""
OLD_VERSION = """
    SELECT stable_id, version FROM descriptions_vh WHERE deleted_at IS NOT NULL
    ORDER BY stable_id, version LIMIT 1
"""
Q6VA95 = """
    SELECT d.stable_id, d.version FROM descriptions_vh AS d
    JOIN proteins AS p ON p.id = d.protein2_id
    WHERE d.deleted_at IS NULL AND p.accession = 'Q6VA95' ORDER BY d.stable_id LIMIT 1
"""
LIVE = "(stable_id, version) = (%(live)s, %(live_version)s)"
OLD = "(stable_id, version) = (%(old)s, %(old_version)s)"

# Each violation uses the rows found by the queries above: %(live)s, %(old)s, %(q6va95)s.
VIOLATIONS = {
    "R3": f"""
        UPDATE proteins SET ncbi_taxon_id = 999999999
        WHERE id = (SELECT protein1_id FROM descriptions_vh WHERE {LIVE})
    """,
    "V2": f"UPDATE descriptions_vh SET version = version + 10 WHERE {LIVE}",
    "V3": f"UPDATE descriptions_vh SET deleted_at = NULL WHERE {OLD}",
    "V4": f"""
        UPDATE descriptions_vh SET deleted_at = deleted_at + interval '10 years' WHERE {OLD}
    """,
    "V5": f"UPDATE descriptions_vh SET deleted_at = created_at - interval '1 day' WHERE {OLD}",
    "V6": f"""
        UPDATE descriptions_vh SET association_id = (SELECT max(id) FROM associations)
        WHERE {OLD} AND association_id <> (SELECT max(id) FROM associations)
    """,
    "V7": "UPDATE descriptions_vh SET stable_id = 'XX00000000' WHERE stable_id = %(live)s",
    "D1": f"UPDATE descriptions_vh SET protein1_id = protein2_id WHERE {LIVE}",
    "D3": f"UPDATE descriptions_vh SET start2 = stop2 + 1 WHERE {LIVE}",
    "D5": f"""
        INSERT INTO descriptions_vh (stable_id, version, association_id, method_id, protein1_id,
            mapping1, protein2_id, name2, start2, stop2, mapping2)
        SELECT 'CW00000000', 1, association_id, method_id, protein1_id,
            mapping1, protein2_id, name2, start2, stop2, mapping2
        FROM descriptions_vh WHERE {LIVE}
    """,
    "D6": """
        UPDATE descriptions_vh SET name2 = 'orf6'
        WHERE (stable_id, version) = (%(q6va95)s, %(q6va95_version)s)
    """,
    "D9": f"""
        UPDATE descriptions_vh
        SET mapping1 = regexp_replace(mapping1::text, '"sequence": *"', '"sequence": "WWWWW')::json
        WHERE {LIVE}
    """,
    "D10": """
        UPDATE descriptions_vh SET stop2 = stop2 - 1
        WHERE (stable_id, version) = (%(q6va95)s, %(q6va95_version)s)
    """,
    "D11": f"""UPDATE descriptions_vh SET mapping1 = '[{{"sequence": 1}}]' WHERE {LIVE}""",
    "D12": f"""
        UPDATE descriptions_vh
        SET mapping1 = regexp_replace(mapping1::text, '"identity": *[0-9.]+', '"identity": 80',
                                      'g')::json
        WHERE {LIVE}
    """,
    "S1": f"""
        UPDATE associations SET state = 'pending'
        WHERE id = (SELECT association_id FROM descriptions_vh WHERE {LIVE})
    """,
    "S5": "INSERT INTO runs (type, name) SELECT type, name FROM runs ORDER BY id LIMIT 1",
}


def ids(conn) -> dict[str, object]:
    found: dict[str, object] = {}
    for name, sql in (("live", LIVE_VH), ("old", OLD_VERSION), ("q6va95", Q6VA95)):
        found[name], found[f"{name}_version"] = conn.execute(sql).fetchone()
    return found


def counts(conn) -> dict[str, int]:
    return {r.invariant.id: len(r.rows) for r in run_checks(conn.cursor())}


def test_fixture_has_no_error(conn):
    assert errors(run_checks(conn.cursor())) == []


def test_every_invariant_is_tested():
    # D2 (obsolete snapshots) is in the fixture as it is.
    assert set(VIOLATIONS) | {"D2"} == {i.id for i in INVARIANTS}


@pytest.mark.parametrize("invariant", sorted(VIOLATIONS))
def test_violation_is_found(conn, invariant):
    before = counts(conn)
    conn.execute(VIOLATIONS[invariant], ids(conn))
    after = counts(conn)
    assert after[invariant] > before[invariant]


def test_a_description_in_the_table_of_another_run_type_is_found(conn):
    before = counts(conn)
    conn.execute(
        """
        INSERT INTO descriptions_hh (stable_id, version, association_id, method_id, protein1_id,
            mapping1, protein2_id, mapping2)
        SELECT 'CW00000000', 1, association_id, method_id, protein1_id, mapping1, protein1_id,
            mapping2
        FROM descriptions_vh WHERE (stable_id, version) = (%(live)s, %(live_version)s)
        """,
        ids(conn),
    )
    assert counts(conn)["D1"] == before["D1"] + 1


def test_checks_see_the_transaction_and_leave_it_usable(conn):
    cur = conn.cursor()
    before = counts(conn)
    cur.execute(VIOLATIONS["D5"], ids(conn))
    assert counts(conn)["D5"] == before["D5"] + 1  # uncommitted, seen; temp tables dropped
    conn.rollback()
    assert counts(conn) == before


def test_extra_end_residues_are_left_out_of_the_occurrences(conn):
    before = counts(conn)
    # WWWWW added before the first mapping, and named as its nter: its occurrences still fit
    conn.execute(
        """
        UPDATE descriptions_vh
        SET mapping1 = jsonb_set(
            jsonb_set(mapping1::jsonb, '{0,sequence}',
                      to_jsonb('WWWWW' || (mapping1->0->>'sequence'))),
            '{0,nter}', '"WWWWW"')::json
        WHERE (stable_id, version) = (%(live)s, %(live_version)s)
        """,
        ids(conn),
    )
    assert counts(conn)["D9"] == before["D9"]
    conn.execute(
        """
        UPDATE descriptions_vh
        SET mapping1 = jsonb_set(mapping1::jsonb, '{0,nter}', '"AAAAA"')::json
        WHERE (stable_id, version) = (%(live)s, %(live_version)s)
        """,
        ids(conn),
    )
    assert counts(conn)["D9"] == before["D9"] + 1


def test_extra_end_residues_must_be_text(conn):
    before = counts(conn)
    conn.execute(
        "UPDATE descriptions_vh SET mapping1 = jsonb_set(mapping1::jsonb, '{0,nter}', '1')::json "
        "WHERE (stable_id, version) = (%(live)s, %(live_version)s)",
        ids(conn),
    )
    assert counts(conn)["D11"] == before["D11"] + 1
