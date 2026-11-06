"""Protein sequences from NCBI (GenBank, RefSeq), for what UniProt lacks: the publication's
strain, whose sequence gives the mappings (`curation/docs/curation-rules.md#mapping`).

    uv run ./curation/scripts/genbank.py search <query>... [--limit <n>]
    uv run ./curation/scripts/genbank.py seq <accession>[:<start>-<stop>]...

- `search`: the GenBank (with EMBL and DDBJ) and RefSeq protein records of each query, never
  NCBI's copies of Swiss-Prot or PDB, in NCBI search syntax (`JFH-1 AND polyprotein`,
  `"Hepatitis C virus JFH-1"[Organism]`), or of a nucleotide accession (a genome: the proteins it
  codes for): accession and version, title, length, taxon (`<ID> <name>`). Bounded and counted as
  `database/scripts/read.py` bounds and counts its lines: `--limit <n>` lines per query (20), a
  list that is cut ending with how many there are.
- `seq`: a protein record: its accession and version, title, length and sequence, or the
  subsequence between those coordinates (1-based, inclusive). A genome's accession is no protein
  record: `search` lists its proteins.

Read-only, no database. One request at a time, at the pace NCBI allows (`NCBI_API_KEY` in the
project's `.env` raises it). An option the script does not define is ignored, never refused.
"""

import argparse

from curation.genbank import LIMIT, Eutils, Page, search, seq

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
commands = parser.add_subparsers(dest="command", required=True)
s = commands.add_parser("search")
s.add_argument("queries", nargs="+")
s.add_argument("--limit", type=int, default=LIMIT)
q = commands.add_parser("seq")
q.add_argument("locations", nargs="+")
args, _ = parser.parse_known_args()  # an option it does not define is ignored, never refused
eutils = Eutils()
if args.command == "search":
    print(search(eutils, args.queries, Page(args.limit)))
else:
    print(seq(eutils, args.locations))
