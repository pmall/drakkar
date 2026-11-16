"""Diff the descriptions of one publication, as curated, against its live descriptions.

A curation gives the whole list of a publication's descriptions, on the current snapshots of its
accessions; the diff says what writing it would change (`files.py`, `diff`). Descriptions are
matched on method, human accession, viral accession and coordinates, empty coordinates being the
full protein, whatever the snapshots of the live one. A matched description whose snapshots,
generic name or mapping sequences differ is revised onto the current snapshots of the curation's
accessions, with the curation's note as it is. A curated description without a match is added, a
live one without a match is deleted. The publication is given, so an empty list deletes every
live description.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from database.write import (
    Description,
    InvalidRow,
    NewDescription,
    Revised,
    Revision,
    live_revisions,
    snapshot_by_id,
    snapshot_of,
)

Key = tuple[str, str, str, int | None, int | None]


@dataclass(frozen=True)
class Diff:
    same: list[str]  # stable IDs of the live descriptions the curation leaves as they are
    added: list[NewDescription]
    revised: list[Revision]
    deleted: list[Revision]


def _label(d: Description) -> str:
    region = "" if d.start2 is None and d.stop2 is None else f"[{d.start2}-{d.stop2}]"
    return f"{d.method} {d.accession1} × {d.accession2}{region}"


def _full_length(cur: Any, accession: str) -> int | None:
    """The length of the current snapshot of an accession, if it has one."""
    cur.execute(
        """
        SELECT length(p.sequences->>p.accession) FROM proteins AS p
        JOIN proteins_versions AS v ON v.accession = p.accession AND v.version = p.version
        WHERE p.accession = %s
        """,
        (accession,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _key(cur: Any, d: Description) -> Key:
    """Method and interactors; empty coordinates are the full current protein."""
    start2 = 1 if d.start2 is None else d.start2
    stop2 = _full_length(cur, d.accession2) if d.stop2 is None else d.stop2
    return d.method, d.accession1, d.accession2, start2, stop2


def _live_key(cur: Any, d: Revised) -> Key:
    """Method, the accessions of the snapshots used, coordinates."""
    accessions = [snapshot_by_id(cur, i).accession for i in (d.protein1_id, d.protein2_id)]
    return d.method, accessions[0], accessions[1], d.start2, d.stop2


def _revised(cur: Any, d: Description) -> Revised:
    """A curated description on the current snapshots of its accessions."""
    try:
        ids = [snapshot_of(cur, a).id for a in (d.accession1, d.accession2)]
    except InvalidRow as e:
        raise ValueError(f"{_label(d)}: {e}") from None
    return Revised(d.method, ids[0], ids[1], d.name2, d.start2, d.stop2, d.mappings1, d.mappings2)


def _changed(live: Revised, curated: Revised) -> bool:
    """Other snapshots, another generic name or other mapping sequences."""
    return (
        (live.protein1_id, live.protein2_id) != (curated.protein1_id, curated.protein2_id)
        or live.name2 != curated.name2
        or set(live.mappings1) != set(curated.mappings1)
        or set(live.mappings2) != set(curated.mappings2)
    )


def diff_descriptions(cur: Any, pmid: int, curated: Sequence[NewDescription]) -> Diff:
    """What writing `curated`, the whole curation of a publication, would change."""
    live = live_revisions(cur, pmid)  # refused for a publication in no vh run
    by_key: dict[Key, NewDescription] = {}
    for item in curated:
        if item.pmid != pmid:
            raise ValueError(
                f"{_label(item.description)} is in publication {item.pmid}, not {pmid}"
            )
        key = _key(cur, item.description)
        if key in by_key:
            raise ValueError(f"{_label(item.description)} is curated twice")
        by_key[key] = item

    diff = Diff([], [], [], [])
    for row in live:
        assert row.description is not None
        item = by_key.pop(_live_key(cur, row.description), None)
        if item is None:
            note = "REMOVED: not found by the curation"
            diff.deleted.append(replace(row, action="remove", description=None, note=note))
        elif _changed(row.description, revised := _revised(cur, item.description)):
            diff.revised.append(replace(row, description=revised, note=item.note))
        else:
            diff.same.append(row.stable_id)
    diff.added.extend(by_key.values())
    return diff
