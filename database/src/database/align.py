"""Mapping occurrences: where a mapping is found on the isoforms of its interactor.

A mapping is the whole sequence used in the experiment; its extra end residues, not on the
interactor (an initiator methionine, residues of the polyprotein past a mature protein, a tag),
are named in `nter` and `cter` and left out of the occurrences. In the files, they are written in
lowercase at the ends of the sequence (`mSTNPK` is `nter` M).

The occurrences follow fixed rules, so a mapping on given sequences always gets the same ones:

1. Exact matches come first: if the mapping is found exactly on an isoform, its occurrences are
   the exact matches, on every isoform that has one.
2. Otherwise the mapping is aligned on each isoform (BLOSUM62, gaps -10/-2, the protein free
   beyond both ends of the mapping; an arbitrary choice: a mapping is right by its sequence, not
   by this alignment). The isoforms that reach the best score keep every placement
   of their optimal alignments, each with the highest identity among its alignments.
3. On each isoform, overlapping placements form one cluster (chains included), which keeps its
   first placement: the smallest start, then the smallest stop.

Identity is identical residues over the alignment length: the mapping plus the protein residues
facing a gap inside it (`docs/glossary.md`). U, O and J, which BLOSUM62 does not score, are
aligned as X.
"""

import re
from functools import cache
from itertools import islice
from typing import Any

from Bio import Align
from Bio.Align import substitution_matrices

MIN_IDENTITY = 90.0  # a mapping written reaches it on one occurrence (docs/glossary.md, identity)
MAX_ALIGNMENTS = 1000  # optimal alignments read on one isoform; more only for degenerate cases
WRITTEN = re.compile(r"([a-z]*)([A-Z]+)([a-z]*)")
UNSCORED = str.maketrans("UOJ", "XXX")

Placement = tuple[int, int, float]  # start, stop (1-based on the region), identity


def read_written(text: str) -> tuple[str, str, str]:
    """(sequence, nter, cter) of a mapping as written in the files; ValueError if malformed."""
    match = WRITTEN.fullmatch(text)
    if match is None:
        raise ValueError(f"mapping {text[:20]}…: lowercase only at its ends, for extra residues")
    nter, _, cter = match.groups()
    return text.upper(), nter.upper(), cter.upper()


def core(mapping: dict[str, Any]) -> str:
    """The part of a mapping located on its interactor: the sequence without `nter` and `cter`."""
    sequence: str = mapping["sequence"]
    return sequence[len(mapping.get("nter", "")) : len(sequence) - len(mapping.get("cter", ""))]


def written(mapping: dict[str, Any]) -> str:
    """A mapping JSON as written in the files: its extra end residues in lowercase."""
    return mapping.get("nter", "").lower() + core(mapping) + mapping.get("cter", "").lower()


def _aligner(overhang: bool) -> Any:  # Biopython is not fully typed
    # The whole mapping is aligned (global); with `overhang`, the protein may extend beyond both
    # ends of the mapping for free.
    aligner = Align.PairwiseAligner(mode="global")
    aligner.substitution_matrix = substitution_matrices.load("BLOSUM62")  # type: ignore
    aligner.open_gap_score = -10
    aligner.extend_gap_score = -2  # long gaps cost more than a few mismatches
    if overhang:
        aligner.end_deletion_score = 0  # protein residues outside the mapping
    return aligner


ALIGNER: Any = _aligner(overhang=True)
SEGMENT_ALIGNER: Any = _aligner(overhang=False)  # a fixed segment: aligned end to end


@cache
def segment_identity(sequence: str, segment: str) -> float:
    """Identity of a mapping aligned end to end on the protein segment of an occurrence."""
    if sequence == segment:
        return 100.0
    alignment: Any = SEGMENT_ALIGNER.align(
        segment.translate(UNSCORED), sequence.translate(UNSCORED)
    )[0]
    counts: Any = alignment.counts()
    columns = len(sequence) + counts.deletions
    return round(100 * counts.identities / columns, 5)


def _exact(sequence: str, region: str) -> list[Placement]:
    """Every exact match of the mapping on the region, overlapping ones included."""
    found: list[Placement] = []
    position = region.find(sequence)
    while position != -1:
        found.append((position + 1, position + len(sequence), 100))
        position = region.find(sequence, position + 1)
    return found


def _aligned(sequence: str, region: str) -> list[Placement]:
    """The placements of the optimal alignments of the mapping on the region, each with the
    highest identity among its alignments. An alignment where no residue of the mapping faces the
    region places nothing."""
    identities: dict[tuple[int, int], float] = {}
    for alignment in islice(ALIGNER.align(region, sequence), MAX_ALIGNMENTS):
        blocks = alignment.aligned[0]  # aligned blocks on the region
        if not len(blocks):
            continue
        bounds = (int(blocks[0][0]) + 1, int(blocks[-1][1]))
        counts: Any = alignment.counts()
        identity = round(100 * counts.identities / (len(sequence) + counts.internal_deletions), 5)
        identities[bounds] = max(identities.get(bounds, 0.0), identity)
    return [(start, stop, identity) for (start, stop), identity in identities.items()]


def _clustered(placements: list[Placement]) -> list[Placement]:
    """The first placement of each cluster of overlapping placements, chains included."""
    kept: list[Placement] = []
    reach = 0  # the last residue covered by the current cluster
    for placement in sorted(placements):
        if placement[0] > reach:
            kept.append(placement)
        reach = max(reach, placement[1])
    return kept


def best_identity(mapping: dict[str, Any]) -> float:
    """The best identity of a mapping JSON over all its occurrences (0 without any)."""
    return max((o["identity"] for i in mapping["isoforms"] for o in i["occurrences"]), default=0.0)


def map_sequence(
    sequence: str,
    isoforms: dict[str, str],
    canonical: str,
    start: int,
    stop: int,
    nter: str = "",
    cter: str = "",
) -> dict[str, Any]:
    """Mapping JSON for one sequence: its occurrences on the isoforms of the interactor, by the
    rules of the module, whatever their identity (the caller judges it against `MIN_IDENTITY`).

    `sequence` is the whole sequence used in the experiment, `nter` and `cter` its extra end
    residues: only the rest is located. Positions on the canonical isoform are relative to the
    region [start, stop], positions on other isoforms to the whole isoform (as checked by D9).
    """
    mapping: dict[str, Any] = {"sequence": sequence}
    if nter:
        mapping["nter"] = nter
    if cter:
        mapping["cter"] = cter
    located = core(mapping)
    regions = {
        isoform: full[start - 1 : stop] if isoform == canonical else full
        for isoform, full in sorted(isoforms.items())
    }
    found = {isoform: _exact(located, region) for isoform, region in regions.items()}
    if not any(found.values()):
        query = located.translate(UNSCORED)
        targets = {isoform: region.translate(UNSCORED) for isoform, region in regions.items()}
        scores = {isoform: ALIGNER.score(target, query) for isoform, target in targets.items()}
        best = max(scores.values())
        found = {
            isoform: _aligned(query, target)
            for isoform, target in targets.items()
            if scores[isoform] == best
        }
    mapping["isoforms"] = [
        {
            "accession": isoform,
            "occurrences": [{"start": a, "stop": b, "identity": i} for a, b, i in _clustered(p)],
        }
        for isoform, p in found.items()
        if p
    ]
    return mapping
