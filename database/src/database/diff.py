"""Diff the descriptions of one publication, as curated, against its live descriptions.

A curation gives the whole list of a publication's descriptions; the diff says what writing it
would change (`database-diff`, `files.py`). Descriptions are matched on what makes them one
description (`docs/glossary.md`): method, human accession, viral accession and coordinates,
empty coordinates being the full protein. A matched description whose generic name or mapping
sequences differ is revised, with the curation's note as it is.
A curated description without a match is added, a live one without a match is deleted. The
publication is given, so an empty list deletes every live description.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from database.write import Description, NewDescription, Revision, live_revisions

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


def _changed(live: Description, curated: Description) -> bool:
    """Another generic name or other mapping sequences."""
    return (
        live.name2 != curated.name2
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
        item = by_key.pop(_key(cur, row.description), None)
        if item is None:
            note = "REMOVED: not found by the curation"
            diff.deleted.append(replace(row, action="remove", description=None, note=note))
        elif _changed(row.description, item.description):
            diff.revised.append(replace(row, description=item.description, note=item.note))
        else:
            diff.same.append(row.stable_id)
    diff.added.extend(by_key.values())
    return diff
