"""Check mapping sequences on an identified entry, as the write will
(`database/src/database/align.py`).

    uv run ./database/scripts/mapping.py <accession>[:<start>-<stop>] <sequence>...

Read-only, on the current snapshots. The interactor is an accession as `read.py` takes it, an
isoform's refused, then its stretch. For each mapping sequence (extra end residues in lowercase):
its extra end residues, its occurrences on each isoform with their identity, in the entry's
numbering, and `ok`, `below 90 %` or `aligns nowhere`; a sequence over 20 residues is shown by its
first 20 and its length. One interactor per call: an accession among the sequences gets its own
line; an interactor that cannot be read (an isoform, coordinates outside the entry), a message
alone. An option the script does not define is ignored, never refused.
"""

import argparse

from database.db import reading
from database.mapping import mapping

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("interactor")
parser.add_argument("sequences", nargs="+")
args, _ = parser.parse_known_args()  # an option it does not define is ignored, never refused
with reading() as cur:
    print(mapping(cur, args.interactor, args.sequences))
