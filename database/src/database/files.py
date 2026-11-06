r"""The files of a pass, and the functions that write them to Drakkar or diff them against it:
`add`, `revise`, `publications`, `batch` and `diff`, run by the scripts of the same names
(`database/scripts/`), which describe them.

Descriptions and publication states are written only through these functions, from files. Without
`commit`, a write is a dry run: it applies its files, checks every invariant on the whole database
in the same transaction, and rolls back. With `commit`, it commits only if nothing is refused and
the check finds no error (`write.py`). A write returns its report and whether it passed: the
refused rows, with their file and line, the errors the check finds, the warnings on the rows
written, then `<n> rows, <n> applied: committed`, `dry run passed, rolled back` or `failed, rolled
back`. A file that cannot be read raises `FileError`, with its file and line.

The files are JSON Lines: one JSON object per line, with every key of its format and no other
(`ADD`, `REVISE`, `PUBLICATIONS`), its values in JSON types. No header: an empty file has no row,
and a blank line is skipped. Every row names its publication by its PMID: a file holds one
publication or many, and files concatenate with `cat`. In a value, JSON escapes only `"` (`\"`),
`\` (`\\`) and line breaks (`\n`). A line with a missing or unknown key, or a value of the wrong
type, is refused with its file and line. The notes follow `docs/database.md#notes`.

Each row is an object of `write.py`, its keys its fields, those of its `Description` in line:
`method`, `accession1`, `accession2`, `start2` and `stop2` (numbers, or null for the full
protein), `name2`, `mappings1` and `mappings2` (lists of mapping sequences).

Descriptions to add (`*.jsonl`), one line per new description, a `NewDescription`: `pmid` (a
number), the keys of its `Description`, `note`. One line, wrapped here:

    {"pmid": 35939498, "method": "MI:0007", "accession1": "Q13501", "accession2": "P29990",
    "start2": null, "stop2": null, "name2": "C", "mappings1": [], "mappings2": ["mSTNPK"],
    "note": "..."}

Revisions (`*.revise.jsonl`, `*.delete.jsonl`), one line per revised or removed description, a
`Revision`: `stable_id`, `version` (a number), `pmid` (a number), `action` (`revise` or
`remove`), `into` (a stable ID, or null), the keys of its `Description` (null on a `remove`,
unless it gives what a merged duplicate was decided to become), `note`.

Publications (`*.jsonl`), one line per publication whose state or note changes, a
`PublicationUpdate`: `pmid` (a number), `state` (`selected` or `curated`), `note`.

    {"pmid": 35939498, "state": "curated", "note": "CURATED ..."}
"""

import json
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, cast

import psycopg

from database.diff import diff_descriptions
from database.write import (
    Description,
    NewDescription,
    Outcome,
    PublicationUpdate,
    Revision,
    add_descriptions,
    revise_descriptions,
    update_publications,
    write_batch,
)

DESCRIPTION = [
    "method",
    "accession1",
    "accession2",
    "start2",
    "stop2",
    "name2",
    "mappings1",
    "mappings2",
]
ADD = ["pmid", *DESCRIPTION, "note"]
REVISE = ["stable_id", "version", "pmid", "action", "into", *DESCRIPTION, "note"]
PUBLICATIONS = ["pmid", "state", "note"]
# The files of a batch: the descriptions to add and the publications, and the files of
# `diff`; a descriptions file may be missing. Of the additions, only the first present is
# read: the descriptions.add.jsonl of a diff is written beside the descriptions.jsonl it comes
# from.
BATCH_REVISIONS = ["descriptions.revise.jsonl", "descriptions.delete.jsonl"]
BATCH_ADDITIONS = ["descriptions.add.jsonl", "descriptions.jsonl"]
BATCH_PUBLICATIONS = "publications.jsonl"


class FileError(ValueError):
    pass


def _json_lines[T](
    paths: Sequence[Path], keys: list[str], parse: Callable[[str, dict[str, Any]], T]
) -> list[tuple[str, T]]:
    """The items of JSON Lines files, as (where, item); blank lines are skipped. Split on `\\n`
    only: a JSON string can hold other line separators."""
    rows: list[tuple[str, T]] = []
    for path in paths:
        for number, line in enumerate(path.read_text().split("\n"), 1):
            if line.strip():
                where = f"{path}:{number}"
                rows.append((where, parse(where, _object(where, line, keys))))
    return rows


def read_descriptions(paths: Sequence[Path]) -> list[tuple[str, NewDescription]]:
    """The descriptions to add of JSON Lines files, as (where, description)."""
    return _json_lines(paths, ADD, new_description)


def read_revisions(paths: Sequence[Path]) -> list[tuple[str, Revision]]:
    """The revisions and removals of JSON Lines files, as (where, revision)."""
    return _json_lines(paths, REVISE, revision)


def read_publications(paths: Sequence[Path]) -> list[tuple[str, PublicationUpdate]]:
    """The publication updates of JSON Lines files, as (where, update)."""
    return _json_lines(paths, PUBLICATIONS, publication)


def _object(where: str, line: str, keys: list[str]) -> dict[str, Any]:
    """A line of JSON: an object with every key of `keys`, and no other."""
    try:
        value: object = json.loads(line)
    except json.JSONDecodeError as e:
        raise FileError(f"{where}: not JSON: {e.msg}, column {e.colno}") from None
    if not isinstance(value, dict):
        raise FileError(f"{where}: not a JSON object")
    row = cast(dict[str, Any], value)
    problems = [
        f"{label} {', '.join(keys)}"
        for label, keys in (
            ("missing", [key for key in keys if key not in row]),
            ("unknown", [key for key in row if key not in keys]),
        )
        if keys
    ]
    if problems:
        raise FileError(f"{where}: {'; '.join(problems)}")
    return row


def _number(where: str, row: dict[str, Any], key: str) -> int:
    value: object = row[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise FileError(f"{where}: {key} is not a number: {value!r}")
    return value


def _text(where: str, row: dict[str, Any], key: str) -> str:
    value: object = row[key]
    if not isinstance(value, str):
        raise FileError(f"{where}: {key} is not a string: {value!r}")
    return value


def _texts(where: str, row: dict[str, Any], key: str) -> tuple[str, ...]:
    value: object = row[key]
    items = cast(list[object], value) if isinstance(value, list) else None
    if items is None or not all(isinstance(item, str) for item in items):
        raise FileError(f"{where}: {key} is not a list of strings: {value!r}")
    return tuple(s.strip() for s in cast(list[str], items) if s.strip())


def _description(where: str, row: dict[str, Any]) -> Description:
    """The description keys of a row, from `method` to `mappings2`."""
    return Description(
        method=_text(where, row, "method").strip(),
        accession1=_text(where, row, "accession1").strip(),
        accession2=_text(where, row, "accession2").strip(),
        start2=None if row["start2"] is None else _number(where, row, "start2"),
        stop2=None if row["stop2"] is None else _number(where, row, "stop2"),
        name2=_text(where, row, "name2").strip(),
        mappings1=_texts(where, row, "mappings1"),
        mappings2=_texts(where, row, "mappings2"),
    )


def new_description(where: str, row: dict[str, Any]) -> NewDescription:
    """A description to add, from its JSON object."""
    return NewDescription(
        _number(where, row, "pmid"),
        _description(where, row),
        _text(where, row, "note"),
    )


def revision(where: str, row: dict[str, Any]) -> Revision:
    """A revision or a removal, from its JSON object. On a `remove`, the description keys are
    null, unless they give what a merged duplicate was decided to become."""
    action = _text(where, row, "action").strip()
    if action not in ("revise", "remove"):
        raise FileError(f"{where}: action is {action!r}, not revise or remove")
    into: object = row["into"]
    if into is not None and not isinstance(into, str):
        raise FileError(f"{where}: into is not a string or null: {into!r}")
    described = any(row[key] is not None for key in DESCRIPTION)
    return Revision(
        stable_id=_text(where, row, "stable_id").strip(),
        version=_number(where, row, "version"),
        pmid=_number(where, row, "pmid"),
        action=action,
        description=_description(where, row) if described else None,
        into=(into or "").strip(),
        note=_text(where, row, "note"),
    )


def publication(where: str, row: dict[str, Any]) -> PublicationUpdate:
    """A publication update, from its JSON object."""
    state = _text(where, row, "state").strip()
    if state not in ("selected", "curated"):
        raise FileError(f"{where}: state is {state!r}, not selected or curated")
    return PublicationUpdate(_number(where, row, "pmid"), state, _text(where, row, "note"))


def _description_values(d: Description | None) -> dict[str, Any]:
    """The description keys of a row, null without a description."""
    if d is None:
        return dict.fromkeys(DESCRIPTION)
    return {
        "method": d.method,
        "accession1": d.accession1,
        "accession2": d.accession2,
        "start2": d.start2,
        "stop2": d.stop2,
        "name2": d.name2,
        "mappings1": list(d.mappings1),
        "mappings2": list(d.mappings2),
    }


def format_new_description(item: NewDescription) -> str:
    """A description to add as a line of JSON (the inverse of `new_description`)."""
    values = {
        "pmid": item.pmid,
        **_description_values(item.description),
        "note": item.note,
    }
    return json.dumps(values, ensure_ascii=False)


def format_revision(item: Revision) -> str:
    """A revision as a line of JSON (the inverse of `revision`)."""
    values = {
        "stable_id": item.stable_id,
        "version": item.version,
        "pmid": item.pmid,
        "action": item.action,
        "into": item.into or None,
        **_description_values(item.description),
        "note": item.note,
    }
    return json.dumps(values, ensure_ascii=False)


def _write_lines(path: Path, lines: Iterable[str]) -> None:
    """A JSON Lines file, empty when there is no line."""
    path.write_text("".join(line + "\n" for line in lines))


def write_descriptions(path: Path, items: Sequence[NewDescription]) -> None:
    _write_lines(path, map(format_new_description, items))


def write_revisions(path: Path, items: Sequence[Revision]) -> None:
    _write_lines(path, map(format_revision, items))


# --- Tools --------------------------------------------------------------------------------------


def report(outcome: Outcome, wheres: Sequence[str]) -> str:
    """What happened, short: refused rows (`wheres`, a place per row), check errors, warnings on
    what was written."""
    lines = [f"refused {wheres[number - 1]}: {why}" for number, why in outcome.problems]
    for result in outcome.errors:
        lines.append(f"error {result.invariant.id}: {result.invariant.title}")
        lines.append("  " + "\t".join(result.header))
        lines += ["  " + "\t".join(str(v) for v in row) for row in result.rows[:20]]
        if len(result.rows) > 20:
            lines.append(f"  … {len(result.rows) - 20} more")
    written = set(outcome.written)
    for result in outcome.results:
        if result.invariant.severity != "warning" or "stable_id" not in result.header:
            continue
        column = result.header.index("stable_id")
        if mine := [row for row in result.rows if row[column] in written]:
            lines.append(f"warning {result.invariant.id}: {result.invariant.title}")
            lines.append("  " + "\t".join(result.header))
            lines += ["  " + "\t".join(str(v) for v in row) for row in mine]
    if outcome.committed:
        verdict = "committed"
    elif outcome.ok:
        verdict = "dry run passed, rolled back"
    else:
        verdict = "failed, rolled back"
    lines.append(f"{len(wheres)} rows, {len(outcome.written)} applied: {verdict}")
    return "\n".join(lines)


def _write(
    read: Callable[[Sequence[Path]], list[tuple[str, Any]]],
    write: Callable[..., Outcome],
    conn: psycopg.Connection,
    paths: Sequence[Path],
    **options: Any,
) -> tuple[str, bool]:
    """The report of a write of files, and whether it passed."""
    rows = read(paths)
    outcome = write(conn, [item for _, item in rows], **options)
    return report(outcome, [where for where, _ in rows]), outcome.ok


def add(conn: psycopg.Connection, paths: Sequence[Path], *, commit: bool) -> tuple[str, bool]:
    """Adds the descriptions of the files."""
    return _write(read_descriptions, add_descriptions, conn, paths, commit=commit)


def revise(conn: psycopg.Connection, paths: Sequence[Path], *, commit: bool) -> tuple[str, bool]:
    """Revises and removes the descriptions of the files, checked on the result of all rows."""
    return _write(read_revisions, revise_descriptions, conn, paths, commit=commit)


def publications(
    conn: psycopg.Connection, paths: Sequence[Path], *, author: str, commit: bool
) -> tuple[str, bool]:
    """Writes the publication states and notes of the files, `author` the notes' author."""
    return _write(read_publications, update_publications, conn, paths, author=author, commit=commit)


def batch(
    conn: psycopg.Connection, directory: Path, *, author: str, commit: bool
) -> tuple[str, bool]:
    """Writes a batch from the files of its directory, in one transaction: the revisions and
    removals, the new descriptions, then the publication states and notes."""

    def present(names: list[str]) -> list[Path]:
        return [directory / name for name in names if (directory / name).exists()]

    revision_rows = read_revisions(present(BATCH_REVISIONS))
    addition_rows = read_descriptions(present(BATCH_ADDITIONS)[:1])
    publication_rows = read_publications([directory / BATCH_PUBLICATIONS])
    outcome = write_batch(
        conn,
        [item for _, item in revision_rows],
        [item for _, item in addition_rows],
        [item for _, item in publication_rows],
        author=author,
        commit=commit,
    )
    wheres = [where for where, _ in [*revision_rows, *addition_rows, *publication_rows]]
    return report(outcome, wheres), outcome.ok


def diff(cur: Any, pmid: int, path: Path) -> str:
    """Diffs the descriptions of the file against the live descriptions of the publication, writes
    beside the file what writing it would change, and says what it wrote. A publication in no vh
    run, or a file of another publication, raises `ValueError`."""
    items = [item for _, item in read_descriptions([path])]
    found = diff_descriptions(cur, pmid, items)
    stem = path.with_suffix("")
    added = stem.with_name(f"{stem.name}.add.jsonl")
    write_descriptions(added, found.added)
    lines = [f"PMID {pmid}: {len(found.same)} same", f"{len(found.added)} to add: {added}"]
    for kind, revisions in (("revise", found.revised), ("delete", found.deleted)):
        out = stem.with_name(f"{stem.name}.{kind}.jsonl")
        write_revisions(out, revisions)
        lines.append(f"{len(revisions)} to {kind}: {out}")
    return "\n".join(lines)
