"""Keep the files of the generic viral proteins in step with Drakkar (read-only on the database).

    uv run ./database/scripts/generic.py sync <dir>

The files, their formats and the species they give are described in
`database/src/database/generic.py`.

`sync` rewrites the three files of the directory, sorted, and from Drakkar the families and
publications of `species.tsv` and the names of `proteins.tsv`: the names the dataset no longer
has are removed, the new ones added with an empty `protein`. It prints the counts, the names
removed, then what a person decides, or `nothing`: a species missing from the NCBI taxonomy; a
placed taxon now under its species in it (its line can go); a taxon under no species, with its
lineage and its names; a name with no protein; a name whose protein is a name of the species
mapped to another protein. A file whose header is not its format is refused.
"""

import argparse
import sys
from pathlib import Path

from database.db import reading
from database.generic import sync

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
commands = parser.add_subparsers(dest="command", required=True)
s = commands.add_parser("sync")
s.add_argument("directory", type=Path)
args = parser.parse_args()
try:
    with reading() as cur:
        print(sync(cur, args.directory))
except ValueError as e:  # a file whose header is not its format
    sys.exit(str(e))
