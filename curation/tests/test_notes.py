"""The publications file of a curation batch, from its notes, run as the script."""

import json
import subprocess
import sys
from pathlib import Path


def run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    """A script of `scripts/`, run with this Python."""
    path = Path(__file__).parents[1] / "scripts" / f"{script}.py"
    return subprocess.run([sys.executable, path, *args], capture_output=True, text=True)


def rows(path: Path) -> list[dict[str, int | str]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_notes_script_writes_the_publications_of_a_batch(tmp_path: Path):
    """One row per note, the PMID its directory's name, the state from its first word, the note as
    written; a directory without a note, and the merged files, are left out."""
    notes = {
        "22046132": "CURATED: co-IP of SARS-CoV N with NEDD4\n- Not kept: N × B — only cited\n",
        "25031347": "SELECTED: no full text, closed — not open access anywhere\n",
    }
    for pmid, note in notes.items():
        (tmp_path / pmid).mkdir()
        (tmp_path / pmid / "curation.txt").write_text(note)
    (tmp_path / "38566321").mkdir()  # left out of the batch: no note
    (tmp_path / "descriptions.jsonl").write_text("")

    result = run("notes", str(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == f"1 curated, 1 selected: {tmp_path / 'publications.jsonl'}\n"
    assert rows(tmp_path / "publications.jsonl") == [
        {"pmid": 22046132, "state": "curated", "note": notes["22046132"].strip()},
        {"pmid": 25031347, "state": "selected", "note": notes["25031347"].strip()},
    ]


def test_notes_script_never_refuses_a_note(tmp_path: Path):
    """A non-empty note without the SELECTED header is `curated`, whatever it holds, left to the
    write's check; an empty note, or a directory not named by a PMID, gives no row."""
    notes = {
        "22046132": b"co-IP of N\n",
        "25031347": b"CURATED co-IP of \xff\n",
        "38566321": b"\n",
        "notes": b"x",
    }
    for name, note in notes.items():
        (tmp_path / name).mkdir()
        (tmp_path / name / "curation.txt").write_bytes(note)

    result = run("notes", str(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == f"2 curated, 0 selected: {tmp_path / 'publications.jsonl'}\n"
    assert rows(tmp_path / "publications.jsonl") == [
        {"pmid": 22046132, "state": "curated", "note": "co-IP of N"},
        {"pmid": 25031347, "state": "curated", "note": "CURATED co-IP of �"},
    ]
