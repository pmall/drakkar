"""Upgrade the Drakkar proteins to a new UniProt release.

    uv run ./database/scripts/uniprot.py parse <workdir>/<release>
    uv run ./database/scripts/uniprot.py upgrade <workdir>/<release> [--commit]

Run after `taxonomy.py`, on the same directory, named after the release. It reads the UniProt FTP
files: `uniprot_sprot_human.xml.gz` (human, Swiss-Prot), `uniprot_sprot_viruses.xml.gz` and
`uniprot_trembl_viruses.xml.gz` (all viruses), `uniprot_sprot_varsplic.fasta.gz` (isoforms).

Files are scoped by release: `<workdir>/<release>/` holds `taxonomy/` (the NCBI taxdump loaded with
this release), `uniprot/` (the FTP files and their parsed TSV) and `reports/`.

Two steps:

1. `parse`: each XML file of `uniprot/` is converted into a TSV file next to it; one already
   there is kept.
2. `upgrade`: the TSV files are staged, then, in one transaction (without `--commit`, a dry run
   that rolls back):
   - an entry keeps its existing snapshot, and the descriptions on it stay valid, when the
     snapshot is unchanged: same accession, same taxon, exactly the same isoform sequences, and
     for a human entry the same primary gene name, as a curation relies on it (viral names are
     not compared, the curator setting the generic name independently of UniProt; description
     changes are ignored); any other entry gets a new `proteins` row, its old snapshot obsolete;
   - `proteins_versions` is rebuilt: one row per entry of the release, pointing to its snapshot,
     new or kept, with whether it is in Swiss-Prot (`reviewed`) and its secondary accessions; an
     accession removed from UniProt (deleted, merged, demerged) gets no row, its snapshots
     obsolete too;
   - the reports: `reports/uniprot_upgrade.md`, what changed, with the entries whose taxon is
     missing from the taxonomy, printed, and `reports/obsolete_vh_descriptions.tsv`, the
     descriptions that need a revision. A release already in `proteins` is refused.

The steps are logged on stderr.
"""

import argparse
import sys
from pathlib import Path

from database.db import connect
from database.uniprot import parse, upgrade

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
commands = parser.add_subparsers(dest="command", required=True)
parse_parser = commands.add_parser("parse")
parse_parser.add_argument("release_directory", type=Path)
upgrade_parser = commands.add_parser("upgrade")
upgrade_parser.add_argument("release_directory", type=Path)
upgrade_parser.add_argument("--commit", action="store_true")
args = parser.parse_args()
if args.command == "parse":
    parse(args.release_directory)
else:
    try:
        with connect() as conn:
            print(upgrade(conn, args.release_directory, commit=args.commit))
    except ValueError as e:  # a release already in proteins
        sys.exit(str(e))
