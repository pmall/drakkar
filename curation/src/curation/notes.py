"""The publications file of a curation batch, from its publication notes.

uv run curation-notes <dir>
    writes `<dir>/publications.jsonl` from each `<dir>/<pmid>/curation.txt`, as written: one row
    per note, the PMID its directory's name, the state `selected` when the note starts with
    `SELECTED`, `curated` otherwise; an empty note gives no row. It never refuses a note: the
    write checks the file.
"""

import argparse
import json
from pathlib import Path
from typing import cast

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("dir", type=Path)
    args = parser.parse_args()
    directory = cast(Path, args.dir)
    rows = read_notes(directory)
    out = directory / PUBLICATIONS
    out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    states = [row["state"] for row in rows]
    print(f"{states.count('curated')} curated, {states.count('selected')} selected: {out}")
