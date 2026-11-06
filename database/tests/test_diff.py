"""The diff of a curated publication against its live descriptions, and its script."""

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from database.diff import diff_descriptions
from database.files import read_revisions, write_descriptions
from database.write import Description, NewDescription, live_revisions

SARS = 22046132  # Q6VA95 `N` carried by EY73D2C965 and EYF737084C
SELECTED = 25031347
NEW = NewDescription(SELECTED, Description("MI:0007", "P46934", "P25223", "P"))  # NEDD4


def live_as_curated(conn, pmid: int) -> dict[str, NewDescription]:
    """The live descriptions of a publication, as a curation that finds them all would give them."""
    rows = {
        r.stable_id: NewDescription(pmid, r.description, "Fig. 1")
        for r in live_revisions(conn.cursor(), pmid)
        if r.description is not None
    }
    conn.rollback()
    return rows


def diff(conn, pmid, items):
    result = diff_descriptions(conn.cursor(), pmid, list(items))
    conn.rollback()
    return result


def test_the_same_curation_changes_nothing(conn):
    curated = live_as_curated(conn, SARS)
    result = diff(conn, SARS, curated.values())
    assert sorted(result.same) == sorted(curated)
    assert not result.added and not result.revised and not result.deleted


def test_empty_coordinates_are_the_full_protein(conn):
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
        "UPDATE descriptions SET deleted_at = now() WHERE association_id = "
        "(SELECT id FROM associations WHERE pmid = %s)",
        (SELECTED,),
    )
    result = diff(conn, SELECTED, [NEW])
    assert result.added == [NEW]
    assert not result.same and not result.revised and not result.deleted


def test_another_name_or_other_mappings_are_a_revision(conn):
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
    assert revised.description == curated["EY73D2C965"].description
    assert revised.note == "Y2H (MI:0018), Table S1\n- Mapping: 1–26 (Fig. 3)"  # as curated
    assert "EY73D2C965" not in result.same and not result.added and not result.deleted


def test_another_method_or_interactor_is_a_deletion_and_an_addition(conn):
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


def test_diff_script_writes_files_the_write_tools_take(conn, tmp_path: Path):
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
