"""Check the Drakkar invariants (`database/docs/database.md#invariants`) on vh and hh data,
without writing.

    uv run ./database/scripts/check.py <dir>

The report, written to the directory (`<workdir>/<release>/reports/check`, say), is a Markdown
summary, `check.md`, plus one TSV file per violated invariant, `<invariant>.tsv`, one row per
violation, with the stable ID and PMID when relevant. The exit code is 1 if any error is found.
"""

import argparse
import sys
from pathlib import Path

from database.check import run
from database.db import connect

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("output", type=Path)
args = parser.parse_args()
with connect() as conn:
    text, ok = run(conn, args.output)
print(text)
sys.exit(0 if ok else 1)
