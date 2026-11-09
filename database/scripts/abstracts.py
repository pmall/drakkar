"""Print the titles and abstracts of a run's pending publications (read-only).

    uv run ./database/scripts/abstracts.py <run ID> <offset> <count>

The run's `pending` publications, ordered by PMID, `<count>` of them from `<offset>` (from 0),
each as a block of four lines, `PMID <pmid>`, `Types: <publication types>`, `Title: <title>`,
`Abstract: <abstract>`, as plain text (tags removed, entities decoded), the blocks separated by a
blank line. Exits with 1 when it fails.
"""

import argparse
import sys

from database.db import reading
from database.pubmed import abstracts

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("run", type=int, help="the run's ID")
parser.add_argument("offset", type=int)
parser.add_argument("count", type=int)
args = parser.parse_args()
try:
    with reading() as cur:
        print(abstracts(cur, args.run, args.offset, args.count))
except ValueError as e:
    sys.exit(str(e))
