"""Write a batch to Drakkar, from the files of its directory.

    uv run ./database/scripts/batch.py <dir> [--author <name>] [--commit]

The files: `descriptions.jsonl`, the descriptions to add; `descriptions.add.jsonl`,
`descriptions.revise.jsonl` and `descriptions.delete.jsonl`, the files `diff.py` writes beside a
`descriptions.jsonl`, the first read in place of `descriptions.jsonl` when it is there; and
`publications.jsonl`. A missing descriptions file has no rows. One transaction, in this order: the
revisions and removals, the new descriptions, the publication states and notes, `--author` naming
the author of the notes. Every invariant is checked once, on the result, so a row can rely on an
earlier one (an addition on a rename).

Without `--commit`, a dry run. The files, the dry run, the commit and the report it prints are
described in `database/src/database/files.py`. Exits with 1 when it fails or a file cannot be
read.
"""

import argparse
import sys
from pathlib import Path

from database.db import connect
from database.files import batch

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("dir", type=Path)
parser.add_argument("--author", default="")
parser.add_argument("--commit", action="store_true")
args = parser.parse_args()
try:
    with connect() as conn:
        text, ok = batch(conn, args.dir, author=args.author, commit=args.commit)
except ValueError as e:  # a file that cannot be read, or a stable ID given twice
    sys.exit(str(e))
print(text)
sys.exit(0 if ok else 1)
