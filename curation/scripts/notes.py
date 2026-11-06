"""The publications file of a curation batch, from its publication notes.

    uv run ./curation/scripts/notes.py <dir>

Writes `<dir>/publications.jsonl` from each `<dir>/<pmid>/curation.txt`, as written: one row per
note, the PMID its directory's name, the state `selected` when the note starts with `SELECTED`,
`curated` otherwise; an empty note gives no row. It never refuses a note: the write checks the file.
Prints how many are curated and selected, and the file's path.
"""

import argparse
from pathlib import Path

from curation.notes import PUBLICATIONS, write_publications

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("dir", type=Path)
args = parser.parse_args()
states = [row["state"] for row in write_publications(args.dir)]
out = args.dir / PUBLICATIONS
print(f"{states.count('curated')} curated, {states.count('selected')} selected: {out}")
