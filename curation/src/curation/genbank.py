"""Protein sequences from NCBI (GenBank, RefSeq), for what UniProt lacks: the publication's
strain, whose sequence gives the mappings (`docs/curation-rules.md#mapping`).

    uv run curation-genbank search <query>... [--limit <n>]
    uv run curation-genbank seq <accession>[:<start>-<stop>]...

- `search`: the GenBank (with EMBL and DDBJ) and RefSeq protein records of each query, never
  NCBI's copies of Swiss-Prot or PDB, in NCBI search syntax (`JFH-1 AND polyprotein`,
  `"Hepatitis C virus JFH-1"[Organism]`), or of a nucleotide accession (a genome: the proteins it
  codes for): accession and version, title, length, taxon (`<ID> <name>`). Bounded and counted as
  `database-read` bounds and counts its lines: `--limit <n>` lines per query (20), a list that is
  cut ending with how many there are.
- `seq`: a protein record: its accession and version, title, length and sequence, or the
  subsequence between those coordinates (1-based, inclusive). A genome's accession is no protein
  record: `search` lists its proteins.

Read-only, no database. One request at a time, at the pace NCBI allows (`NCBI_API_KEY` in the
project's `.env` raises it). An option the command does not define is ignored, never refused.
"""

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlencode

from dotenv import load_dotenv

from curation.fetch import EFETCH, Get, http_get, parse_args

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ESEARCH = f"{EUTILS}/esearch.fcgi"
# The records a search keeps: GenBank's (with EMBL's and DDBJ's) and RefSeq's, not NCBI's copies
# of Swiss-Prot or PDB.
SOURCES = "srcdb_genbank[PROP] OR srcdb_embl[PROP] OR srcdb_ddbj[PROP] OR srcdb_refseq[PROP]"
ESUMMARY = f"{EUTILS}/esummary.fcgi"
ELINK = f"{EUTILS}/elink.fcgi"
ACCESSION = re.compile(r"[A-Z]+_?\d+(?:\.\d+)?")  # AF177036, NC_045512.2
LOCATION = re.compile(r"([A-Za-z0-9_.]+?)(?::(\d+)-(\d+))?")  # BAB32872.1:1-191
TITLE = 120  # characters shown of a title: those of Swiss-Prot records list every name
LIMIT = 20  # lines per input by default


@dataclass(frozen=True)
class Page:
    """At most `limit` lines per input, the best first; a list that is cut ends with how many
    there are, and the limit that cut it."""

    limit: int = LIMIT

    def cut[T](self, items: list[T]) -> list[T]:
        return items[: self.limit]

    def lines(self, label: str, lines: list[str], total: int | None = None) -> list[str]:
        """An input's lines, each after its label, cut to the page; `lines` may already be the
        page, of `total` lines."""
        total = len(lines) if total is None else total
        if not total:
            return [f"{label}\t(none)"]
        shown = [f"{label}\t{line}" for line in self.cut(lines)]
        if len(shown) < total:
            shown.append(f"{label}\t… {len(shown)} of {total} shown, cut by --limit {self.limit}")
        return shown


DEFAULT = Page()


def _title(text: str) -> str:
    return text if len(text) <= TITLE else f"{text[:TITLE]}…"


class Eutils:
    """Requests to the NCBI E-utilities, spaced as NCBI asks: 3 per second, 10 with a key."""

    def __init__(self, get: Get = http_get, pause: float | None = None) -> None:
        load_dotenv()
        self.get = get
        self.key = os.environ.get("NCBI_API_KEY")
        self.pause = (0.11 if self.key else 0.34) if pause is None else pause
        self.last = 0.0

    def __call__(self, url: str, **params: Any) -> tuple[int, str]:
        wait = self.last + self.pause - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        params = {**params, "tool": "curation", **({"api_key": self.key} if self.key else {})}
        r = self.get(f"{url}?{urlencode(params)}")
        self.last = time.monotonic()
        return r.status, r.body.decode(errors="replace")


def _fasta(text: str) -> list[tuple[str, str]]:
    """(header, sequence) of each record of a FASTA text."""
    records: list[tuple[str, str]] = []
    for block in text.split(">")[1:]:
        header, _, body = block.partition("\n")
        records.append((header.strip(), "".join(body.split())))
    return records


def seq(eutils: Eutils, locations: list[str]) -> str:
    """The sequence of each protein record, or between its coordinates. A genome's accession is no
    protein record: `search` lists its proteins."""
    lines = ["#location\taccession\ttitle\tlength\tsequence"]
    for text in locations:
        match = LOCATION.fullmatch(text)
        if match is None:
            lines.append(f"{text}\tnot <accession>[:<start>-<stop>]")
            continue
        accession, start, stop = match.groups()
        status, body = eutils(EFETCH, db="protein", id=accession, rettype="fasta", retmode="text")
        records = _fasta(body) if status == 200 else []
        if records:
            header, sequence = records[0]
            found, _, title = header.partition(" ")
            if start is not None and stop is not None:
                first, last = int(start), int(stop)
                if not 1 <= first <= last <= len(sequence):
                    lines.append(f"{text}\t{first}-{last} is not a stretch of 1-{len(sequence)}")
                    continue
                sequence = sequence[first - 1 : last]
            lines.append(f"{text}\t{found}\t{_title(title)}\t{len(sequence)}\t{sequence}")
        else:
            lines.append(f"{text}\tno protein record at NCBI (a genome: search lists its proteins)")
    return "\n".join(lines)


def _summaries(eutils: Eutils, ids: list[str]) -> list[str]:
    """A line per protein record: accession and version, title, length, taxon (`<ID> <name>`)."""
    if not ids:
        return []
    status, body = eutils(ESUMMARY, db="protein", id=",".join(ids), retmode="json")
    summaries = cast(dict[str, Any], json.loads(body)["result"]) if status == 200 else {}
    rows: list[str] = []
    for uid in ids:
        s = cast(dict[str, Any], summaries.get(uid, {}))
        rows.append(
            f"{s.get('accessionversion', uid)}\t{_title(s.get('title', '?'))}\t"
            f"{s.get('slen', '?')}\t{s.get('taxid', '?')} {s.get('organism', '?')}"
        )
    return rows


def _coded(eutils: Eutils, accession: str) -> list[str]:
    """The protein records a nucleotide record codes for, by NCBI's link, in its order."""
    status, body = eutils(ESEARCH, db="nuccore", term=f"{accession}[accn]", retmode="json")
    ids = (
        cast(list[str], json.loads(body)["esearchresult"].get("idlist", []))
        if status == 200
        else []
    )
    if not ids:
        return []
    status, body = eutils(ELINK, dbfrom="nuccore", db="protein", id=ids[0], retmode="json")
    if status != 200:
        return []
    links: list[str] = []
    for linkset in cast(list[dict[str, Any]], json.loads(body).get("linksets", [])):
        for found in cast(list[dict[str, Any]], linkset.get("linksetdbs", [])):
            if found.get("linkname") == "nuccore_protein":
                links += cast(list[str], found.get("links", []))
    return links


def search(eutils: Eutils, queries: list[str], page: Page = DEFAULT) -> str:
    """The GenBank and RefSeq protein records of each query, in NCBI's order: a page of them, and
    how many. A nucleotide accession, which the protein search does not find, gives the protein
    records it codes for."""
    lines = ["#query\taccession\ttitle\tlength\ttaxon"]
    for query in queries:
        term = f"({query}) AND ({SOURCES})"
        status, body = eutils(ESEARCH, db="protein", term=term, retmax=page.limit, retmode="json")
        if status != 200:
            lines.append(f"{query}\tNCBI search failed (HTTP {status})")
            continue
        result = cast(dict[str, Any], json.loads(body)["esearchresult"])
        ids = cast(list[str], result.get("idlist", []))
        total = int(result.get("count", 0))
        if not total and ACCESSION.fullmatch(query):
            ids = _coded(eutils, query)
            total = len(ids)
        lines += page.lines(query, _summaries(eutils, page.cut(ids)), total)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    s = commands.add_parser("search")
    s.add_argument("queries", nargs="+")
    s.add_argument("--limit", type=int, default=LIMIT)
    q = commands.add_parser("seq")
    q.add_argument("locations", nargs="+")
    args = parse_args(parser)
    eutils = Eutils()
    if args.command == "search":
        print(search(eutils, args.queries, Page(args.limit)))
    else:
        print(seq(eutils, args.locations))
