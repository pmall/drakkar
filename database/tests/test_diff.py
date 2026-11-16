"""The diff of a curated publication against its live descriptions, and its script."""

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from database.diff import diff_descriptions
from database.files import read_revisions, write_descriptions
from database.write import Description, NewDescription, Revised, live_revisions, snapshot_by_id

SARS = 22046132  # Q6VA95 `N` carried by EY73D2C965 and EYF737084C
OBSOLETE = 10777214  # its human interactor Q16635 on an obsolete snapshot
SELECTED = 25031347
NEW = NewDescription(SELECTED, Description("MI:0007", "P46934", "P25223", "P"))  # NEDD4


@pytest.fixture
def sars(conn) -> None:
    """SARS on current UniProt only, as a curation is: without EY23A90501, whose viral entry
    Q6SRE2 has left UniProt."""
    conn.execute(
        "UPDATE descriptions_vh SET deleted_at = now() "
        "WHERE stable_id = 'EY23A90501' AND deleted_at IS NULL"
    )
    conn.commit()


def as_curated(cur, d: Revised) -> Description:
    """A live description as a curation gives it: the accessions of its snapshots."""
    a1, a2 = (snapshot_by_id(cur, i).accession for i in (d.protein1_id, d.protein2_id))
    return Description(d.method, a1, a2, d.name2, d.start2, d.stop2, d.mappings1, d.mappings2)


def live_as_curated(conn, pmid: int) -> dict[str, NewDescription]:
    """The live descriptions of a publication, as a curation that finds them all would give them."""
    cur = conn.cursor()
    rows = {
        r.stable_id: NewDescription(pmid, as_curated(cur, r.description), "Fig. 1")
        for r in live_revisions(cur, pmid)
        if r.description is not None
    }
    conn.rollback()
    return rows


def diff(conn, pmid, items):
    result = diff_descriptions(conn.cursor(), pmid, list(items))
    conn.rollback()
    return result


def test_the_same_curation_changes_nothing(conn, sars):
    curated = live_as_curated(conn, SARS)
    result = diff(conn, SARS, curated.values())
    assert sorted(result.same) == sorted(curated)
    assert not result.added and not result.revised and not result.deleted


def test_empty_coordinates_are_the_full_protein(conn, sars):
    curated = live_as_curated(conn, SARS)
    n = curated["EY73D2C965"]
    assert (n.description.accession2, n.description.start2, n.description.stop2) == (
        "Q6VA95",
        1,
        63,
    )
    curated["EY73D2C965"] = replace(n, description=replace(n.description, start2=None, stop2=None))
    assert "EY73D2C965" in diff(conn, SARS, curated.values()).same


def test_a_new_publication_gives_only_additions(conn):
    conn.execute(  # a selected publication without descriptions, in this transaction only
        "UPDATE descriptions_vh SET deleted_at = now() WHERE association_id = "
        "(SELECT id FROM associations WHERE pmid = %s)",
        (SELECTED,),
    )
    result = diff(conn, SELECTED, [NEW])
    assert result.added == [NEW]
    assert not result.same and not result.revised and not result.deleted


def test_another_name_or_other_mappings_are_a_revision(conn, sars):
    live = {r.stable_id: r for r in live_revisions(conn.cursor(), SARS)}
    conn.rollback()
    curated = live_as_curated(conn, SARS)
    n = curated["EY73D2C965"]
    curated["EY73D2C965"] = replace(
        n,
        description=replace(
            n.description, name2="orf9b", mappings2=("MDPNQTNVVPPALHLVDPQIQLTITR",)
        ),
        note="Y2H (MI:0018), Table S1\n- Mapping: 1–26 (Fig. 3)",
    )
    result = diff(conn, SARS, curated.values())
    [revised] = result.revised
    assert (revised.stable_id, revised.version, revised.action) == ("EY73D2C965", 1, "revise")
    assert revised.description == replace(
        live["EY73D2C965"].description,
        name2="orf9b",
        mappings2=("MDPNQTNVVPPALHLVDPQIQLTITR",),
    )
    assert revised.note == "Y2H (MI:0018), Table S1\n- Mapping: 1–26 (Fig. 3)"  # as curated
    assert "EY73D2C965" not in result.same and not result.added and not result.deleted


def test_another_method_or_interactor_is_a_deletion_and_an_addition(conn, sars):
    curated = live_as_curated(conn, SARS)
    n = curated.pop("EY73D2C965")
    other = replace(n, description=replace(n.description, method="MI:0007"))
    result = diff(conn, SARS, [*curated.values(), other])
    assert result.added == [other]
    [deleted] = result.deleted
    assert (deleted.stable_id, deleted.action, deleted.description) == (
        "EY73D2C965",
        "remove",
        None,
    )
    assert deleted.note == "REMOVED: not found by the curation"


def test_a_description_on_an_obsolete_snapshot_is_revised_onto_the_current_one(conn):
    """The same curation of a publication whose human interactor Q16635 is on an obsolete
    snapshot: both descriptions revised onto the current snapshot of Q16635, nothing else."""
    curated = live_as_curated(conn, OBSOLETE)
    current = conn.execute(
        "SELECT p.id FROM proteins AS p JOIN proteins_versions AS v "
        "ON v.accession = p.accession AND v.version = p.version WHERE p.accession = 'Q16635'"
    ).fetchone()[0]
    conn.rollback()
    result = diff(conn, OBSOLETE, curated.values())
    assert sorted(r.stable_id for r in result.revised) == sorted(curated)
    assert all(r.description and r.description.protein1_id == current for r in result.revised)
    assert not result.same and not result.added and not result.deleted


def test_an_accession_with_no_current_snapshot_is_refused(conn):
    """EY23A90501 curated on Q6SRE2, which has left UniProt."""
    with pytest.raises(ValueError, match="Q6SRE2 has no current snapshot"):
        diff(conn, SARS, live_as_curated(conn, SARS).values())


def test_an_empty_curation_deletes_every_live_description(conn):
    live = live_as_curated(conn, SARS)
    result = diff(conn, SARS, [])
    assert sorted(r.stable_id for r in result.deleted) == sorted(live)
    assert not result.same and not result.added and not result.revised


def test_a_description_of_another_publication_is_refused(conn):
    with pytest.raises(ValueError, match="is in publication 25031347, not 22046132"):
        diff(conn, SARS, [NEW])


def test_a_description_curated_twice_is_refused(conn):
    with pytest.raises(ValueError, match="curated twice"):
        diff(conn, SELECTED, [NEW, replace(NEW, note="Fig. 2")])


def test_a_publication_in_no_vh_run_is_refused(conn):
    with pytest.raises(ValueError, match="publication 15471871 is in no vh run"):
        diff(conn, 15471871, [])  # in an hh run


# --- The script ---------------------------------------------------------------------------------


def run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    """A script of `scripts/`, run with this Python."""
    path = Path(__file__).parents[1] / "scripts" / f"{script}.py"
    return subprocess.run([sys.executable, path, *args], capture_output=True, text=True)


def test_diff_script_writes_files_the_write_tools_take(conn, sars, tmp_path: Path):
    curated = live_as_curated(conn, SARS)
    del curated["EY73D2C965"], curated["EYF737084C"]  # the two `N`: deleted
    added = NewDescription(
        SARS,
        Description("MI:0007", "P46934", "Q6VA95", "N"),
        "anti-tag co-IP (MI:0007), Fig. 2B",
    )
    path = tmp_path / "descriptions.jsonl"
    write_descriptions(path, [*curated.values(), added])

    result = run("diff", str(SARS), str(path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [
        f"PMID 22046132: {len(curated)} same",
        f"1 to add: {tmp_path / 'descriptions.add.jsonl'}",
        f"0 to revise: {tmp_path / 'descriptions.revise.jsonl'}",
        f"2 to delete: {tmp_path / 'descriptions.delete.jsonl'}",
    ]
    deleted = [item for _, item in read_revisions([tmp_path / "descriptions.delete.jsonl"])]
    assert sorted(r.stable_id for r in deleted) == ["EY73D2C965", "EYF737084C"]
    assert read_revisions([tmp_path / "descriptions.revise.jsonl"]) == []

    # The files are those of the write tools: deleting the two `N` frees Q6VA95[1-63] for the
    # addition, which passes once they are gone.
    removed = run("revise", str(tmp_path / "descriptions.delete.jsonl"), "--commit")
    assert removed.returncode == 0 and "committed" in removed.stdout, removed.stdout
    add = run("add", str(tmp_path / "descriptions.add.jsonl"))
    assert add.returncode == 0 and "dry run passed" in add.stdout, add.stdout


def test_diff_script_refuses_another_publication(dbname, tmp_path: Path):
    path = tmp_path / "descriptions.jsonl"
    write_descriptions(path, [NEW])
    result = run("diff", str(SARS), str(path))
    assert result.returncode == 1 and "is in publication 25031347, not 22046132" in result.stderr
    assert not (tmp_path / "descriptions.add.jsonl").exists()
