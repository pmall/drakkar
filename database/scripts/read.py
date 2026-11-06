"""Read what a curation decision needs from Drakkar, on its current snapshots (read-only).

    uv run ./database/scripts/read.py methods <text>...
    uv run ./database/scripts/read.py taxon <text>...
    uv run ./database/scripts/read.py entry <accession>...
    uv run ./database/scripts/read.py search <text>... [--taxon <ID>]
    uv run ./database/scripts/read.py seq <accession>[:<start>-<stop>]...
    uv run ./database/scripts/read.py closest <sequence> --taxon <ID>
    uv run ./database/scripts/read.py names <taxon ID>...
    uv run ./database/scripts/read.py sql <query>

Each command takes many inputs, except `closest`, one sequence, and `sql`, one query. `entry`
prints a block per entry; the others tab-separated lines under one `#` header line naming the
columns, each line starting with the input it answers when there are many (`(none)` when nothing
is found), the best first. `--limit <n>` bounds the lines per input (20), except in `names`,
never cut; a list that is cut ends with a line `… 20 of 622 shown, cut by --limit 20`. A text
matches as a substring, case aside, except in `methods`. An option a command does not define is
ignored, never refused.

`search` and `entry` identify entries: they take an accession as publications write it
(`written_accession`, `written_accessions`), an old (secondary) accession, an isoform's
(`P30875-2`), a sequence version (`P04637.2`), a group (`P09913; O14879`, `Q15646;`, each of its
accessions), case aside; it names its current entry, or, for an old accession, the current entries
that hold it (one after a merge, several after a split), never an obsolete one
(`current_entries`). `seq` and `mapping.py` take an accession the same way, then its
stretch. A taxon is given by its NCBI ID and covers its whole subtree; it is written
`<ID> <name>`, a lineage `<ID> <name> < …` up to the family. A stretch of a protein is written
`<accession>:<start>-<stop>`. An input that cannot be read gets its own line, with why.

- `methods`: the PSI-MI terms with a name or a synonym that holds a word of the text, case and
  punctuation aside (`biolayer interferometry` finds `bio-layer interferometry`, `GST pull-down`
  finds `pull down`), the closest names first (the most words held), then the detection methods
  (MI:0001), then the most used: PSI-MI ID, name (with the synonym matched), `is_detection`, live
  descriptions.
- `taxon`: the taxa one of whose names contains each text and that hold a current entry (theirs
  or under them), the closest names first (a name that is the text, then one that starts with it
  as a word, holds it as a word, holds it inside a word): the taxon (with the name matched), its
  rank, its lineage.
- `entry`: each entry's lineage, gene names, length, isoforms, chains, peptides, propeptides,
  domains, zinc fingers and regions, and for a viral entry the generic names of the live
  descriptions on its current snapshot, each with its span and its live descriptions; for an old
  accession, the current entries that hold it.
- `search`: the entries each text names, under the taxon when given, Swiss-Prot first: an
  accession, its current entries, or, when it names none, the entries with a gene name that is
  the text (`B3GAT1` has an accession's shape); any other text, the entries whose `search` text
  (accession, gene names, taxon, protein name) contains it. Each line: the accession to write,
  `SP` (Swiss-Prot) or `TR` (TrEMBL), gene name, protein name, taxon, length. An entry whose taxon
  is missing from the NCBI taxonomy is found without `--taxon`, or with its own taxon ID.
- `seq`: the sequence of each entry or isoform, or between those coordinates (1-based,
  inclusive).
- `closest`: the entries of the taxon closest to the amino acid sequence (an accession is
  refused), by a database search: every isoform is aligned on the sequence (Smith-Waterman,
  BLOSUM62, gap open 11, extension 1, by pyopal), and each entry is ranked by the score of its
  best isoform, then Swiss-Prot first: each entry as `search` shows it, then identity (identical
  residues over the aligned columns, gaps included), coverage (the part of the sequence aligned),
  aligned region (`1-15` on the canonical isoform, `<isoform>:1-15` on another). Sequences after
  the first are not searched, with a warning.
- `names`: the generic names of the viral interactors of live descriptions under each taxon, on
  current snapshots, the most used first, with their live descriptions and their three most used
  interactors; never cut.
- `sql`: free SQL for what no command gives, on a read-only connection where each statement stops
  after 30 seconds: its rows, whole, as tab-separated lines under a `#` header of column names.
  The query bounds its own rows and columns; past 10 kB of output, a guard of the context, the
  rest is left out, with a line `… cut at 10 kB: select fewer columns or rows`; an error, as
  PostgreSQL gives it. Written from the tables of `database/docs/database.md#tables`.
"""

import argparse

from database.db import reading
from database.read import LIMIT, Page, closest, entries, methods, names, search, seq, sql, taxa

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
commands = parser.add_subparsers(dest="command", required=True)
limit = argparse.ArgumentParser(add_help=False)
limit.add_argument("--limit", type=int, default=LIMIT)
m = commands.add_parser("methods", parents=[limit])
m.add_argument("texts", nargs="+")
t = commands.add_parser("taxon", parents=[limit])
t.add_argument("texts", nargs="+")
e = commands.add_parser("entry")
e.add_argument("accessions", nargs="+")
s = commands.add_parser("search", parents=[limit])
s.add_argument("texts", nargs="+")
s.add_argument("--taxon", type=int)
c = commands.add_parser("closest", parents=[limit])
c.add_argument("sequence")
c.add_argument("more", nargs="*", help=argparse.SUPPRESS)  # not searched, warned after
c.add_argument("--taxon", type=int, required=True)
q = commands.add_parser("seq")
q.add_argument("locations", nargs="+")
n = commands.add_parser("names")
n.add_argument("taxa", nargs="+", type=int)
x = commands.add_parser("sql")
x.add_argument("query")
args, _ = parser.parse_known_args()  # an option a read does not define is ignored, never refused
with reading() as cur:
    if args.command == "methods":
        print(methods(cur, args.texts, Page(args.limit)))
    elif args.command == "taxon":
        print(taxa(cur, args.texts, Page(args.limit)))
    elif args.command == "entry":
        print(entries(cur, args.accessions))
    elif args.command == "search":
        print(search(cur, args.texts, args.taxon, Page(args.limit)))
    elif args.command == "closest":
        print(closest(cur, args.sequence, args.taxon, Page(args.limit)))
        if args.more:
            print(
                f"warning: {len(args.more)} more sequence{'s' if len(args.more) > 1 else ''} "
                "not searched: closest searches the first only"
            )
    elif args.command == "seq":
        print(seq(cur, args.locations))
    elif args.command == "names":
        print(names(cur, args.taxa))
    else:
        print(sql(cur, args.query))
