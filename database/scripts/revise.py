"""Revise and remove descriptions of Drakkar, from files of revisions.

    uv run ./database/scripts/revise.py <file>... [--commit]

The rows are checked on the result of all of them, so a change that passes through an inconsistent
state is fine (a rename carried by several descriptions, a fix plus a merge). Without `--commit`, a
dry run. The files, the dry run, the commit and the report it prints are described in
`database/src/database/files.py`. Exits with 1 when it fails or a file cannot be read.
"""

import argparse
import sys
from pathlib import Path

from database.db import connect
from database.files import revise

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("files", type=Path, nargs="*")
parser.add_argument("--commit", action="store_true")
args = parser.parse_args()
try:
    with connect() as conn:
        text, ok = revise(conn, args.files, commit=args.commit)
except ValueError as e:  # a file that cannot be read, or a stable ID given twice
    sys.exit(str(e))
print(text)
sys.exit(0 if ok else 1)
