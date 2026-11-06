"""Load or update the NCBI taxonomy (`taxon`, `taxon_name`) for a UniProt release.

    uv run ./database/scripts/taxonomy.py <workdir>/<release> [--commit]

The first script of a release, before `uniprot.py`, on the same directory, named after the
release. The taxonomy is scoped by UniProt release: the dump loaded with a release is kept next to
it, in `<workdir>/<release>/taxonomy/`, the NCBI `taxdump.tar.gz` unpacked (`nodes.dmp`,
`names.dmp`, `merged.dmp`); how it is loaded is described in `database/src/database/taxonomy.py`.
Everything runs in one transaction. Without `--commit`, a dry run: it is rolled back. Its steps are
logged on stderr.
"""

import argparse
from pathlib import Path

from database.db import connect
from database.taxonomy import load

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("release_directory", type=Path)
parser.add_argument("--commit", action="store_true")
args = parser.parse_args()
with connect() as conn:
    load(conn, args.release_directory, commit=args.commit)
