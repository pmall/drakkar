"""Writes: one transaction per list, checked on the whole database, committed only on demand."""

from dataclasses import replace

import pytest

from database.write import (
    Description,
    NewDescription,
    PublicationUpdate,
    Revision,
    add_descriptions,
    live_revisions,
    revise_descriptions,
    update_publications,
    write_batch,
)

SARS = 22046132  # Q6VA95 `N` carried by EY73D2C965 and EYF737084C
RABIES = 38566321
SELECTED = 25031347
HH = 15471871  # in an hh run


def live(conn, pmid) -> dict[str, Revision]:
    rows = {r.stable_id: r for r in live_revisions(conn.cursor(), pmid)}
    conn.rollback()
    return rows


def count(conn) -> int:
    result = conn.execute("SELECT count(*) FROM descriptions_vh").fetchone()[0]
    conn.rollback()
    return result


def renamed(revision: Revision, name2: str, note: str = "") -> Revision:
    assert revision.description is not None
    return replace(revision, description=replace(revision.description, name2=name2), note=note)


# --- Adding -------------------------------------------------------------------------------------


@pytest.fixture
def new(conn) -> NewDescription:
    """NEDD4 with P25223 `P`, mapped by the first 20 residues of P25223."""
    sequence = conn.execute(
        "SELECT p.sequences->>p.accession FROM proteins AS p JOIN proteins_versions AS v "
        "ON v.accession = p.accession AND v.version = p.version WHERE p.accession = 'P25223'"
    ).fetchone()[0]
    conn.rollback()
    return NewDescription(
        SELECTED,
        Description("MI:0007", "P46934", "P25223", "P", mappings2=(sequence[:20],)),
        "anti-tag co-IP (MI:0007), Fig. 2B",
    )


def test_add_dry_run_writes_nothing(conn, new):
    before = count(conn)
    outcome = add_descriptions(conn, [new])
    assert outcome.ok and not outcome.committed and len(outcome.written) == 1
    assert count(conn) == before


def test_add_commits(conn, new):
    outcome = add_descriptions(conn, [new], commit=True)
    assert outcome.ok and outcome.committed
    [stable_id] = outcome.written
    assert stable_id.startswith("CW")
    row = conn.execute(
        "SELECT version, name2, start2, stop2, mapping2, annotation "
        "FROM descriptions_vh WHERE stable_id = %s",
        (stable_id,),
    ).fetchone()
    version, name2, start2, stop2, mapping2, note = row
    assert (version, name2, start2) == (1, "P", 1)
    assert stop2 > 1
    assert mapping2[0]["isoforms"][0]["occurrences"][0] == {"start": 1, "stop": 20, "identity": 100}
    assert note == "anti-tag co-IP (MI:0007), Fig. 2B"


def test_add_refuses_a_bad_row_and_writes_none(conn, new):
    bad = replace(new, description=replace(new.description, accession2="NOTANACC"))
    before = count(conn)
    outcome = add_descriptions(conn, [new, bad], commit=True)
    assert not outcome.committed
    assert [number for number, _ in outcome.problems] == [2]
    assert count(conn) == before


def test_add_duplicate_is_caught_by_the_full_check(conn, new):
    outcome = add_descriptions(conn, [new, new], commit=True)
    assert not outcome.problems  # each row is valid on its own
    assert [r.invariant.id for r in outcome.errors] == ["D5"]
    assert not outcome.committed


def test_add_to_a_publication_in_no_vh_run_is_refused(conn, new):
    outcome = add_descriptions(conn, [replace(new, pmid=15471871)])  # in an hh run
    assert outcome.problems[0][1] == "publication 15471871 is in no vh run"


def test_add_to_a_publication_in_several_vh_runs_is_refused(conn, new):
    conn.execute("INSERT INTO runs (type, name) VALUES ('vh', '99')")
    conn.execute(
        "INSERT INTO associations (run_id, pmid, state) "
        "SELECT id, %s, 'selected' FROM runs WHERE name = '99'",
        (SELECTED,),
    )
    conn.commit()
    outcome = add_descriptions(conn, [new])
    assert outcome.problems[0][1] == f"publication {SELECTED} is in several vh runs: 32, 99"


def test_a_mapping_below_90_percent_is_skipped(conn, new):
    [sequence] = new.description.mappings2
    both = (sequence, "WWWWWWWWWWWWWWWWWWWW")
    outcome = add_descriptions(
        conn, [replace(new, description=replace(new.description, mappings2=both))], commit=True
    )
    assert outcome.ok
    [mapping] = conn.execute(
        "SELECT mapping2 FROM descriptions_vh WHERE stable_id = %s", outcome.written
    ).fetchone()[0]
    assert mapping["sequence"] == sequence


# --- Revising -----------------------------------------------------------------------------------


def test_rename_an_interactor_carried_by_two_descriptions(conn):
    rows = live(conn, SARS)
    note = "name2 N → orf6, Drakkar name of the protein"
    revisions = [renamed(rows[s], "orf6", note) for s in ("EY73D2C965", "EYF737084C")]
    outcome = revise_descriptions(conn, revisions, commit=True)
    assert outcome.ok and outcome.committed
    names = conn.execute(
        "SELECT stable_id, version, name2 FROM descriptions_vh WHERE deleted_at IS NULL "
        "AND stable_id IN ('EY73D2C965', 'EYF737084C') ORDER BY stable_id"
    ).fetchall()
    assert names == [("EY73D2C965", 2, "orf6"), ("EYF737084C", 2, "orf6")]


def test_rename_one_of_two_breaks_one_name_per_interactor(conn):
    rows = live(conn, SARS)
    outcome = revise_descriptions(conn, [renamed(rows["EY73D2C965"], "orf6")], commit=True)
    assert not outcome.problems
    assert [r.invariant.id for r in outcome.errors] == ["D6"]
    assert not outcome.committed


def test_revision_on_a_stale_version_is_refused(conn):
    revision = renamed(live(conn, SARS)["EY73D2C965"], "orf6")
    outcome = revise_descriptions(conn, [replace(revision, version=revision.version + 1)])
    assert "live version is" in outcome.problems[0][1]


def test_revision_that_changes_nothing_is_refused(conn):
    revision = live(conn, SARS)["EY73D2C965"]
    assert "changes nothing" in revise_descriptions(conn, [revision]).problems[0][1]


def test_revision_that_changes_only_a_skipped_mapping_is_skipped(conn):
    revision = live(conn, SARS)["EY73D2C965"]
    assert revision.description is not None
    mappings2 = (*revision.description.mappings2, "WWWWWWWWWWWWWWWWWWWW")
    low = replace(revision, description=replace(revision.description, mappings2=mappings2))
    outcome = revise_descriptions(conn, [low])
    assert not outcome.problems and outcome.written == []


def test_revision_of_another_publication_is_refused(conn):
    revision = renamed(live(conn, SARS)["EY73D2C965"], "orf6")
    outcome = revise_descriptions(conn, [replace(revision, pmid=RABIES)])
    assert f"is a description of publication {SARS}, not {RABIES}" in outcome.problems[0][1]


def test_stable_id_twice_is_refused(conn):
    revision = renamed(live(conn, SARS)["EY73D2C965"], "orf6")
    with pytest.raises(ValueError, match="twice"):
        revise_descriptions(conn, [revision, revision])


def test_merge_a_description_decided_to_be_a_duplicate(conn):
    # EYC9AE3284 (NEDD4, A4UHQ0 M) is decided to be NEDD4 with P25223 P: EY10BAD696.
    rows = live(conn, RABIES)
    removed = rows["EYC9AE3284"]
    assert removed.description is not None
    decided = replace(removed.description, accession2="P25223", name2="P", start2=1, stop2=202)
    merge = replace(
        removed,
        action="remove",
        into="EY10BAD696",
        description=decided,
        note="REMOVED: duplicate of EY10BAD696, the protein tested is P",
    )
    outcome = revise_descriptions(conn, [merge], commit=True)
    assert outcome.ok and outcome.committed
    assert "EYC9AE3284" not in live(conn, RABIES)


def test_merge_of_different_descriptions_is_refused(conn):
    removed = live(conn, RABIES)["EYC9AE3284"]
    merge = replace(
        removed,
        action="remove",
        into="EY10BAD696",
        description=None,
        note="REMOVED: duplicate",
    )
    assert "not duplicates" in revise_descriptions(conn, [merge]).problems[0][1]


def test_removal_needs_no_note(conn):
    """The live version is deleted, its note left as it was."""
    query = "SELECT annotation, deleted_at IS NOT NULL FROM descriptions_vh WHERE stable_id = %s"
    before = conn.execute(f"{query} AND deleted_at IS NULL", ("EYC9AE3284",)).fetchone()[0]
    conn.rollback()
    removed = replace(live(conn, RABIES)["EYC9AE3284"], action="remove", description=None)
    assert removed.note == "" and revise_descriptions(conn, [removed], commit=True).committed
    after = conn.execute(f"{query} ORDER BY version DESC LIMIT 1", ("EYC9AE3284",)).fetchone()
    conn.rollback()
    assert after == (before, True)


def hh_revision(conn) -> Revision:
    """EY1F03BBEB, a live hh description, revised to another method."""
    a1, a2, method = conn.execute(
        """
        SELECT p1.accession, p2.accession, m.psimi_id FROM descriptions_hh AS d
        JOIN proteins AS p1 ON p1.id = d.protein1_id
        JOIN proteins AS p2 ON p2.id = d.protein2_id
        JOIN methods AS m ON m.id = d.method_id
        WHERE d.stable_id = 'EY1F03BBEB' AND d.deleted_at IS NULL
        """
    ).fetchone()
    conn.rollback()
    other = "MI:0018" if method != "MI:0018" else "MI:0007"
    return Revision("EY1F03BBEB", 2, HH, "revise", Description(other, a1, a2), note="FIXED: method")


def test_revise_an_hh_description(conn):
    outcome = revise_descriptions(conn, [hh_revision(conn)], commit=True)
    assert outcome.ok and outcome.committed
    versions = conn.execute(
        "SELECT version, deleted_at IS NULL FROM descriptions_hh WHERE stable_id = 'EY1F03BBEB' "
        "ORDER BY version"
    ).fetchall()
    assert versions == [(1, False), (2, False), (3, True)]


def test_a_stable_id_live_in_both_tables_is_refused(conn):
    conn.execute(
        """
        INSERT INTO descriptions_vh (stable_id, version, association_id, method_id, protein1_id,
            mapping1, protein2_id, name2, start2, stop2, mapping2)
        SELECT stable_id, version, association_id, method_id, protein1_id, mapping1,
            protein2_id, 'X', 1, 1, mapping2
        FROM descriptions_hh WHERE stable_id = 'EY1F03BBEB' AND deleted_at IS NULL
        """
    )
    conn.commit()
    outcome = revise_descriptions(conn, [hh_revision(conn)])
    assert outcome.problems[0][1] == "EY1F03BBEB is live in both tables"


# --- Publications -------------------------------------------------------------------------------


def test_publication_curated(conn):
    note = "CURATED: no description, a review of earlier screens\n- Full text: PMC1234567 (cc by)"
    update = PublicationUpdate(SELECTED, "curated", note)
    assert update_publications(conn, [update], commit=True).committed
    state, ai_pass_at = conn.execute(
        "SELECT state, ai_pass_at IS NOT NULL FROM associations WHERE pmid = %s",
        (SELECTED,),
    ).fetchone()
    assert (state, ai_pass_at) == ("curated", True)


def test_publication_note_goes_first(conn):
    """SELECTED has no note yet; then each note goes first, the previous ones after `---`, after
    the date of the write."""
    first = PublicationUpdate(SELECTED, "selected", "SELECTED: no full text, closed")
    assert update_publications(conn, [first], commit=True).committed
    dated = f"[{today(conn)}] SELECTED: no full text, closed"
    assert note_of(conn, SELECTED) == dated
    note = "CURATED: co-IP of NS1 with TRIM25\n- Full text: PDF provided by the user"
    assert update_publications(conn, [replace(first, state="curated", note=note)], commit=True).ok
    assert note_of(conn, SELECTED) == f"[{today(conn)}] {note}\n---\n{dated}"


def test_publication_note_is_taken_as_written(conn):
    """The state is the update's; the note, whatever its first line, is stored after the date."""
    update = PublicationUpdate(SELECTED, "curated", "co-IP of NS1 with TRIM25")
    assert update_publications(conn, [update], commit=True).committed
    assert note_of(conn, SELECTED) == f"[{today(conn)}] co-IP of NS1 with TRIM25"


def test_publication_note_names_its_author(conn):
    """The author, when given, goes after the date of the note."""
    update = PublicationUpdate(SELECTED, "curated", "CURATED: co-IP of NS1 with TRIM25")
    assert update_publications(conn, [update], author=" pmall ", commit=True).committed
    assert note_of(conn, SELECTED) == f"[{today(conn)}, pmall] CURATED: co-IP of NS1 with TRIM25"


def today(conn) -> str:
    result = conn.execute("SELECT current_date::text").fetchone()[0]
    conn.rollback()
    return result


def note_of(conn, pmid) -> str:
    result = conn.execute("SELECT annotation FROM associations WHERE pmid = %s", (pmid,))
    note = result.fetchone()[0]
    conn.rollback()
    return note


def test_open_transaction_is_refused(conn, new):
    conn.execute("SELECT 1")
    with pytest.raises(RuntimeError):
        add_descriptions(conn, [new])


def test_extra_end_residues_in_lowercase_are_left_out_of_the_occurrences(conn, new):
    [sequence] = new.description.mappings2
    tagged = replace(new, description=replace(new.description, mappings2=("gst" + sequence,)))
    outcome = add_descriptions(conn, [tagged], commit=True)
    assert outcome.ok
    [mapping] = conn.execute(
        "SELECT mapping2 FROM descriptions_vh WHERE stable_id = %s", outcome.written
    ).fetchone()[0]
    assert mapping["sequence"] == "GST" + sequence and mapping["nter"] == "GST"
    assert mapping["isoforms"][0]["occurrences"][0] == {"start": 1, "stop": 20, "identity": 100}
    row = {r.stable_id: r for r in live_revisions(conn.cursor(), SELECTED)}[outcome.written[0]]
    assert row.description is not None and row.description.mappings2 == ("gst" + sequence,)


def test_the_same_sequence_with_other_extra_residues_is_a_duplicate(conn, new):
    [sequence] = new.description.mappings2
    twice = (sequence, sequence[0].lower() + sequence[1:])
    duplicated = replace(new, description=replace(new.description, mappings2=twice))
    assert "duplicate" in add_descriptions(conn, [duplicated]).problems[0][1]


# --- A batch ------------------------------------------------------------------------------------


NOT_ACCESSIBLE = "SELECTED: no full text, closed — not open access anywhere"


def run_of(conn, pmid) -> tuple[str, str]:
    result = conn.execute(
        "SELECT r.name, a.annotation FROM associations AS a "
        "JOIN runs AS r ON r.id = a.run_id WHERE a.pmid = %s",
        (pmid,),
    ).fetchone()
    conn.rollback()
    return result


def batch(conn) -> tuple[list[Revision], list[NewDescription], list[PublicationUpdate]]:
    """SARS's `N` renamed `orf6` with a new `orf6` description, which holds only after the
    renames; SELECTED left `selected`."""
    rows = live(conn, SARS)
    note = "name2 N → orf6, Drakkar name of the protein"
    revisions = [renamed(rows[s], "orf6", note) for s in ("EY73D2C965", "EYF737084C")]
    added = NewDescription(
        SARS,
        Description("MI:0007", "P46934", "Q6VA95", "orf6"),
        "anti-tag co-IP (MI:0007), Fig. 2B",
    )
    return revisions, [added], [PublicationUpdate(SELECTED, "selected", NOT_ACCESSIBLE)]


def test_batch_writes_everything_in_one_transaction(conn):
    revisions, additions, updates = batch(conn)
    assert [r.invariant.id for r in add_descriptions(conn, additions).errors] == ["D6"]  # alone
    before = count(conn)
    outcome = write_batch(conn, revisions, additions, updates)  # a dry run
    assert outcome.ok and not outcome.committed and count(conn) == before
    outcome = write_batch(conn, revisions, additions, updates, commit=True)
    assert outcome.committed and count(conn) == before + 3
    names = {r.description.name2 for r in live(conn, SARS).values() if r.description}
    assert "orf6" in names and "N" not in names
    assert run_of(conn, SELECTED) == ("32", f"[{today(conn)}] {NOT_ACCESSIBLE}")  # not moved


def test_batch_numbers_rows_across_its_lists(conn):
    revisions, additions, updates = batch(conn)
    bad = replace(additions[0], description=replace(additions[0].description, accession2="X"))
    outcome = write_batch(conn, revisions, [bad], updates, commit=True)
    assert [number for number, _ in outcome.problems] == [3] and not outcome.committed
