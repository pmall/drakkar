"""Add descriptions to Drakkar, from files of descriptions to add.

    uv run ./database/scripts/add.py <file>... [--commit]

Without `--commit`, a dry run. The files, the dry run, the commit and the report it prints are
described in `database/src/database/files.py`. Exits with 1 when it fails or a file cannot be
read.
"""

import argparse
import sys
from pathlib import Path

from database.db import connect
from database.files import add

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("files", type=Path, nargs="*")
parser.add_argument("--commit", action="store_true")
args = parser.parse_args()
try:
    with connect() as conn:
        text, ok = add(conn, args.files, commit=args.commit)
except ValueError as e:  # a file that cannot be read, or a stable ID given twice
    sys.exit(str(e))
print(text)
sys.exit(0 if ok else 1)
