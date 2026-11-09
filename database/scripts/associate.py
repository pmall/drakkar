"""Associate to a run the PMIDs of a PubMed query, among the records entered in PubMed in a window.

    uv run ./database/scripts/associate.py <run ID> <query file> <from> <to>

The query file holds a PubMed query, its line breaks read as spaces. `<from>` and `<to>` are dates,
`YYYY-MM-DD`, inclusive, of entry in PubMed (`[crdt]`). The PMIDs found are associated to the run
as `pending`, except those already associated to another run of its type; the new publications are
inserted without metadata, which `populate.py` fetches. The query and the window are recorded in
the run's `info`. One transaction, committed: no dry run, as nothing is checked but what the tool
does itself. A run that does not exist, or that already has its query, is refused. Prints the PMIDs
found, left out and associated. Exits with 1 when it fails.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from database.db import connect
from database.pubmed import associate

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("run", type=int, help="the run's ID")
parser.add_argument("query", type=Path, help="the query file")
parser.add_argument("start", type=date.fromisoformat, metavar="from")
parser.add_argument("end", type=date.fromisoformat, metavar="to")
args = parser.parse_args()
try:
    with connect() as conn:
        print(associate(conn, args.run, args.query.read_text(), args.start, args.end))
except (ValueError, OSError) as e:
    sys.exit(str(e))
