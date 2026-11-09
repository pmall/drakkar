"""Write the PubMed metadata of a run's publications that have none.

    uv run ./database/scripts/populate.py <run ID>

The run's publications not populated are fetched from PubMed (efetch) and their records written to
`publications.metadata`, in the format of `database/src/database/pubmed.py`, and set populated.
The publications of other runs are not touched. One transaction, committed: no dry run. Prints the
publications populated, and those PubMed does not return, left unpopulated. Exits with 1 when it
fails.
"""

import argparse
import sys

from database.db import connect
from database.pubmed import populate

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("run", type=int, help="the run's ID")
args = parser.parse_args()
try:
    with connect() as conn:
        print(populate(conn, args.run))
except (ValueError, OSError) as e:
    sys.exit(str(e))
