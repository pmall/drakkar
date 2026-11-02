"""Check mapping sequences on an identified entry, as the write will (`align.py`).

    uv run database-mapping <accession>[:<start>-<stop>] <sequence>...

Read-only, on the current snapshots. The interactor is an accession as `database-read` takes it
(`read.py`), an isoform's refused, then its stretch. For each mapping sequence (extra end residues
in lowercase): its extra end residues, its occurrences on each isoform with their identity, in the
entry's numbering, and `ok`, `below 90 %` or `aligns nowhere`; a sequence over 20 residues is
shown by its first 20 and its length. One interactor per call: an accession among the sequences
gets its own line; an interactor that cannot be read (an isoform, coordinates outside the entry),
a message alone. An option the command does not define is ignored, never refused.
"""

import argparse
from typing import Any

from database.align import MIN_IDENTITY, best_identity, map_sequence, read_written
from database.check import AMINO_ACIDS
from database.db import connect, parse_args
from database.read import label_of, location, spaced
from database.write import snapshot_of


def _occurrences(aligned: dict[str, Any], canonical: str, start: int) -> str:
    """The occurrences of a mapping JSON on each isoform, in the entry's numbering: the write's
    positions on the canonical isoform are relative to the interactor's start."""
    return "; ".join(
        f"{i['accession']} "
        + ", ".join(
            f"{o['start'] + shift}-{o['stop'] + shift} ({o['identity']:g} %)"
            for o in i["occurrences"]
        )
        for i in aligned["isoforms"]
        for shift in [start - 1 if i["accession"] == canonical else 0]
    )


def mapping(cur: Any, interactor: str, sequences: list[str]) -> str:
    """What the write computes for each mapping sequence on the interactor (its current
    snapshot): extra end residues, occurrences on each isoform with their identity, in the
    entry's numbering, and whether it is below 90 %."""
    lines = ["#sequence\tnter\tcter\toccurrences\tverdict"]
    try:
        accession, isoform, start, stop = location(cur, interactor)
        if isoform != accession:
            raise ValueError("an interactor is an entry, not an isoform")
        snapshot = snapshot_of(cur, accession)
        start, stop = start or 1, stop or snapshot.length
        if not 1 <= start <= stop <= snapshot.length:
            raise ValueError(f"{start}-{stop} is not a stretch of 1-{snapshot.length}")
    except ValueError as e:  # an `InvalidRow` too
        return f"{interactor}: {e}"
    for text in sequences:
        if why := spaced(text):
            lines.append(f"{label_of(text)}\t{why}")
            continue
        if any(c.isdigit() for c in text):  # an accession, never a sequence
            lines.append(f"{label_of(text)}\tan accession: one interactor per call")
            continue
        try:
            sequence, nter, cter = read_written(text)
        except ValueError as e:
            lines.append(f"{label_of(text)}\t{e}")
            continue
        if not AMINO_ACIDS.fullmatch(sequence):
            lines.append(f"{label_of(text)}\tnot an amino acid sequence")
            continue
        aligned = map_sequence(sequence, snapshot.sequences, accession, start, stop, nter, cter)
        identity = best_identity(aligned)
        verdict = (
            "aligns nowhere"
            if not aligned["isoforms"]
            else f"below {MIN_IDENTITY:g} %"
            if identity < MIN_IDENTITY
            else "ok"
        )
        occurrences = _occurrences(aligned, accession, start)
        lines.append(
            f"{label_of(text)}\t{nter or '-'}\t{cter or '-'}\t{occurrences or '-'}\t{verdict}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("interactor")
    parser.add_argument("sequences", nargs="+")
    args = parse_args(parser)
    with connect(readonly=True) as conn, conn.cursor() as cur:
        cur.execute("SET statement_timeout = '30s'")
        print(mapping(cur, args.interactor, args.sequences))
