"""The publications file of a curation batch, from its publication notes: `write_publications`,
run by `curation/scripts/notes.py`, which describes it.
"""

import json
from pathlib import Path

PUBLICATIONS = "publications.jsonl"
NOTE = "curation.txt"


def read_notes(directory: Path) -> list[dict[str, int | str]]:
    """The row of each publication of a curation batch, from its note `<pmid>/curation.txt` as
    written: `selected` when it starts with `SELECTED`, `curated` otherwise. An empty note, or a
    directory not named by a PMID, gives no row."""
    rows: list[dict[str, int | str]] = []
    for path in sorted(directory.glob(f"*/{NOTE}")):
        note = path.read_text(errors="replace").strip()
        if path.parent.name.isdigit() and note:
            state = "selected" if note.startswith("SELECTED") else "curated"
            rows.append({"pmid": int(path.parent.name), "state": state, "note": note})
    return rows


def write_publications(directory: Path) -> list[dict[str, int | str]]:
    """Writes `<dir>/publications.jsonl` from the notes of the batch, and returns its rows."""
    rows = read_notes(directory)
    (directory / PUBLICATIONS).write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    )
    return rows
