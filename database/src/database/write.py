"""Write descriptions and publication states, for the write tools (`files.py`).

Three functions, one per kind of write: `add_descriptions`, `revise_descriptions`,
`update_publications`; `write_batch` runs the three together.
Each writes its lists in one transaction:

1. every row is applied in its own savepoint; a row with a problem is not written, and its
   problems are reported with its number;
2. every invariant is checked on the whole database as the transaction sees it (`check.py`);
3. the transaction is committed only with `commit=True`, no row problem and no error. Otherwise
   it is rolled back: a dry run is the same code as a commit.

Rows are checked only for what they build on: a `selected` or `curated` publication, the
snapshots, the method, the coordinates, the mappings; never the note. What involves other
descriptions (duplicates, generic names) is left to the full check, on the result of the whole
list: a rename carried by several descriptions passes through inconsistent states and is valid at
the end.
"""

import json
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

import psycopg

from database import check
from database.align import MIN_IDENTITY, best_identity, map_sequence, read_written, written
from database.db import require_idle


class InvalidRow(ValueError):
    def __init__(self, *problems: str) -> None:
        super().__init__("; ".join(problems))
        self.problems = list(problems)


@dataclass(frozen=True)
class Description:
    """What a curator decides for one description.

    `accession1` is the human interactor, `accession2` the viral one in vh, human in hh.
    `start2`/`stop2` default to the full protein; a mature protein gets its coordinates. `name2`
    is the generic name of a viral interactor (in hh, the gene name, derived). Human names and
    coordinates are derived from the snapshots.
    Mappings are the sequences the experiment used, their extra end residues in lowercase
    (`database.align`); their occurrences are computed by `map_sequence`, and a mapping whose best
    identity is below `MIN_IDENTITY` is skipped.
    """

    method: str  # PSI-MI ID, e.g. "MI:0007"
    accession1: str
    accession2: str
    name2: str = ""
    start2: int | None = None
    stop2: int | None = None
    mappings1: tuple[str, ...] = ()
    mappings2: tuple[str, ...] = ()


@dataclass(frozen=True)
class NewDescription:
    """A description to add to a publication, in its vh run, with its note."""

    pmid: int
    description: Description
    note: str = ""


@dataclass(frozen=True)
class Revision:
    """A decision on the live `version` of a description, refused if that version is no longer
    live.

    `revise`: a new version, `version` + 1, holding `description`, with its note; it keeps the
    snapshots of the description, even obsolete, except on a side whose accession changes. A
    revision that changes nothing is refused, unless it changes only skipped mappings: it is then
    skipped. `remove`: no successor, the `REMOVED` line added to the note of the live version.
    With `into`, the removed description is a duplicate merged into that survivor: as it is, or
    as `description` when it was decided to become the survivor, it has the same publication,
    method and interactors, and the survivor holds all its mapping sequences.
    """

    stable_id: str
    version: int
    pmid: int
    action: Literal["revise", "remove"]
    description: Description | None = None
    into: str = ""
    note: str = ""


@dataclass(frozen=True)
class PublicationUpdate:
    """The state of a publication in its vh run (`selected` or `curated`) and the note of a pass."""

    pmid: int
    state: Literal["selected", "curated"]
    note: str


@dataclass
class Outcome:
    written: list[str]  # stable IDs, PMIDs for publications
    problems: list[tuple[int, str]]  # (row number, why) for each problem of a row not written
    results: list[check.Result]  # the full check on the result
    committed: bool

    @property
    def errors(self) -> list[check.Result]:
        return check.errors(self.results)

    @property
    def ok(self) -> bool:
        return not self.problems and not self.errors


# --- The transaction ----------------------------------------------------------------------------


Applied = tuple[list[str], list[tuple[int, str]]]  # what was written, the problems of the rows


def _apply_rows[T](
    cur: Any,
    rows: Sequence[T],
    apply: Callable[[Any, T], str | None],
    first: int = 1,
    order: Callable[[T], int] = lambda _: 0,
) -> Applied:
    """Apply each row in its own savepoint; rows are numbered from `first` in their problems. A row
    applied as None is skipped: nothing written, no problem."""
    written: list[str] = []
    problems: list[tuple[int, str]] = []
    for number, row in sorted(enumerate(rows, first), key=lambda n_row: order(n_row[1])):
        try:
            with cur.connection.transaction():
                done = apply(cur, row)
        except InvalidRow as e:
            problems += [(number, p) for p in e.problems]
            continue
        if done is not None:
            written.append(done)
    return written, problems


def _write(conn: psycopg.Connection, commit: bool, apply: Callable[[Any], Applied]) -> Outcome:
    """Apply the rows in one transaction, check everything, commit or roll back."""
    require_idle(conn)
    with conn.transaction() as tx:
        cur = conn.cursor()
        written, problems = apply(cur)
        results = check.run_checks(cur)
        committed = commit and not problems and not check.errors(results)
        if not committed:
            raise psycopg.Rollback(tx)
    return Outcome(written, sorted(problems, key=lambda p: p[0]), results, committed)


# --- Shared checks ------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Snapshot:
    id: int
    accession: str
    type: str
    gene: str
    sequences: dict[str, str]

    @property
    def length(self) -> int:
        return len(self.sequences[self.accession])


def snapshot_of(cur: Any, accession: str, snapshot_id: int | None = None) -> _Snapshot:
    """The current snapshot of an accession, or the given one (a revision keeps its own)."""
    if snapshot_id is None:
        cur.execute(
            """
            SELECT p.id, p.accession, p.type, p.name, p.sequences::text FROM proteins AS p
            JOIN proteins_versions AS v ON v.accession = p.accession AND v.version = p.version
            WHERE p.accession = %s
            """,
            (accession,),
        )
    else:
        cur.execute(
            "SELECT id, accession, type, name, sequences::text FROM proteins WHERE id = %s",
            (snapshot_id,),
        )
    rows = cur.fetchall()
    if not rows:
        raise InvalidRow(f"{accession} has no current snapshot")
    if len(rows) > 1:
        raise InvalidRow(f"{accession} has {len(rows)} current snapshots")
    id_, accession, type_, gene, text = rows[0]
    raw: Any = json.loads(text)
    sequences = {k: v for k, v in cast(dict[str, Any], raw).items() if isinstance(v, str) and v}
    if accession not in sequences or len(sequences) != len(raw):
        raise InvalidRow(f"{accession} (snapshot {id_}) has a missing or empty sequence")
    if type_ == "h" and not (gene or "").strip():
        raise InvalidRow(f"{accession} (snapshot {id_}) is human without a gene name")
    return _Snapshot(id_, accession, type_, gene or "", sequences)


@dataclass(frozen=True)
class Association:
    id: int
    pmid: int
    run: str  # its name
    run_type: str
    state: str


ASSOCIATION = """
    SELECT a.id, a.pmid, r.name, r.type, a.state
    FROM associations AS a
    JOIN runs AS r ON r.id = a.run_id
"""


def vh_association(cur: Any, pmid: int) -> Association:
    """A publication in its vh run: where new curation is written."""
    cur.execute(ASSOCIATION + "WHERE a.pmid = %s AND r.type = 'vh'", (pmid,))
    found = [Association(*row) for row in cur.fetchall()]
    if not found:
        raise InvalidRow(f"publication {pmid} is in no vh run")
    if len(found) > 1:
        runs = ", ".join(sorted(association.run for association in found))
        raise InvalidRow(f"publication {pmid} is in several vh runs: {runs}")
    return found[0]


def _writable(association: Association) -> Association:
    """A publication `selected` or `curated`: where descriptions are written."""
    if association.state not in ("selected", "curated"):
        raise InvalidRow(
            f"publication {association.pmid} of run {association.run} is {association.state}"
        )
    return association


def _build(
    cur: Any,
    association: Association,
    item: Description,
    kept: tuple[tuple[str, int], tuple[str, int]] | None = None,
) -> dict[str, Any]:
    """The columns of a description; raise `InvalidRow` with every problem found.

    `kept` is the (accession, snapshot ID) of each side of a revised description: a side that
    keeps its accession keeps its snapshot, even obsolete; otherwise the current snapshot.
    """
    problems: list[str] = []
    cur.execute("SELECT id FROM methods WHERE psimi_id = %s", (item.method,))
    method = cur.fetchone()
    if method is None:
        problems.append(f"unknown method {item.method}")
    snapshots: list[_Snapshot] = []
    expected = ("h", "v" if association.run_type == "vh" else "h")
    for side, accession in enumerate((item.accession1, item.accession2)):
        pinned = kept[side][1] if kept and kept[side][0] == accession else None
        try:
            snapshot = snapshot_of(cur, accession, pinned)
        except InvalidRow as e:
            problems += [f"protein {side + 1}: {p}" for p in e.problems]
            continue
        if snapshot.type != expected[side]:
            problems.append(
                f"protein {side + 1}: {accession} is {'human' if snapshot.type == 'h' else 'viral'}"
            )
        snapshots.append(snapshot)
    if problems:
        raise InvalidRow(*problems)
    p1, p2 = snapshots

    start2 = 1 if item.start2 is None else item.start2
    stop2 = p2.length if item.stop2 is None else item.stop2
    if association.run_type == "hh":
        name2 = p2.gene
        if (start2, stop2) != (1, p2.length):
            problems.append(f"protein 2: a human interactor is 1-{p2.length}, not {start2}-{stop2}")
    else:
        name2 = item.name2.strip()
        if not name2:
            problems.append("protein 2: the generic name is empty")
        if not 1 <= start2 <= stop2 <= p2.length:
            problems.append(f"protein 2: {start2}-{stop2} is outside 1-{p2.length}")
    if problems:
        raise InvalidRow(*problems)

    mappings: list[list[dict[str, Any]]] = []
    for side, snapshot, sequences, start, stop in (
        (1, p1, item.mappings1, 1, p1.length),
        (2, p2, item.mappings2, start2, stop2),
    ):
        if len({s.upper() for s in sequences}) != len(sequences):
            problems.append(f"protein {side}: duplicate mapping sequences")
        computed: list[dict[str, Any]] = []
        for text in sequences:
            try:
                sequence, nter, cter = read_written(text)
            except ValueError as e:
                problems.append(f"protein {side}: {e}")
                continue
            if not check.AMINO_ACIDS.fullmatch(sequence):
                problems.append(
                    f"protein {side}: mapping {sequence[:20]}… is not an amino acid sequence"
                )
                continue
            mapping = map_sequence(
                sequence, snapshot.sequences, snapshot.accession, start, stop, nter, cter
            )
            if best_identity(mapping) >= MIN_IDENTITY:
                computed.append(mapping)
        mappings.append(computed)
    if problems:
        raise InvalidRow(*problems)
    return {
        "association_id": association.id,
        "method_id": method[0],  # type: ignore[index]
        "protein1_id": p1.id,
        "name1": p1.gene,
        "start1": 1,
        "stop1": p1.length,
        "mapping1": json.dumps(mappings[0]),
        "protein2_id": p2.id,
        "name2": name2,
        "start2": start2,
        "stop2": stop2,
        "mapping2": json.dumps(mappings[1]),
    }


def _insert(cur: Any, stable_id: str, version: int, row: dict[str, Any], note: str) -> None:
    cur.execute(
        """
        INSERT INTO descriptions (stable_id, version, association_id, method_id,
            protein1_id, name1, start1, stop1, mapping1,
            protein2_id, name2, start2, stop2, mapping2, annotation)
        VALUES (%(stable_id)s, %(version)s, %(association_id)s, %(method_id)s,
            %(protein1_id)s, %(name1)s, %(start1)s, %(stop1)s, %(mapping1)s,
            %(protein2_id)s, %(name2)s, %(start2)s, %(stop2)s, %(mapping2)s, %(annotation)s)
        """,
        {**row, "stable_id": stable_id, "version": version, "annotation": note},
    )


# --- Adding -------------------------------------------------------------------------------------


def _new_stable_id(cur: Any) -> str:
    """A `CW` stable ID unused by any row, live or deleted."""
    while True:
        candidate = "CW" + secrets.token_hex(4).upper()
        cur.execute("SELECT 1 FROM descriptions WHERE stable_id = %s", (candidate,))
        if cur.fetchone() is None:
            return candidate


def _add(cur: Any, item: NewDescription) -> str:
    association = _writable(vh_association(cur, item.pmid))
    note = item.note.strip()
    row = _build(cur, association, item.description)
    stable_id = _new_stable_id(cur)
    _insert(cur, stable_id, 1, row, note)
    return stable_id


def add_descriptions(
    conn: psycopg.Connection, items: Sequence[NewDescription], *, commit: bool = False
) -> Outcome:
    """Add new descriptions, each with a new `CW` stable ID, version 1."""
    return write_batch(conn, [], items, [], commit=commit)


# --- Revising -----------------------------------------------------------------------------------


def _live(cur: Any, revision: Revision) -> tuple[int, int, Association]:
    """The live row of a revision's stable ID, locked: its row ID, version and publication."""
    cur.execute(
        "SELECT id, version, association_id FROM descriptions "
        "WHERE stable_id = %s AND deleted_at IS NULL FOR UPDATE",
        (revision.stable_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise InvalidRow(f"{revision.stable_id} has no live version")
    id_, version, association_id = row
    if version != revision.version:
        raise InvalidRow(
            f"{revision.stable_id}: decided on version {revision.version}, "
            f"but the live version is {version}"
        )
    cur.execute(ASSOCIATION + "WHERE a.id = %s", (association_id,))
    association = _writable(Association(*cur.fetchone()))
    if association.pmid != revision.pmid:
        raise InvalidRow(
            f"{revision.stable_id} is a description of publication {association.pmid}, "
            f"not {revision.pmid}"
        )
    return id_, version, association


# The live version of a stable ID: what a revision keeps, and what makes it a duplicate.
LIVE_DESCRIPTION = """
    SELECT d.association_id, d.method_id, p1.accession, p1.id, p2.accession, p2.id,
           d.start2, d.stop2, d.mapping1::text, d.mapping2::text
    FROM descriptions AS d
    JOIN proteins AS p1 ON p1.id = d.protein1_id
    JOIN proteins AS p2 ON p2.id = d.protein2_id
    WHERE d.stable_id = %s AND d.deleted_at IS NULL
"""

# The columns `_build` gives.
COLUMNS = """
    SELECT association_id, method_id, protein1_id, name1, start1, stop1, mapping1,
           protein2_id, name2, start2, stop2, mapping2
    FROM descriptions WHERE id = %s
"""


def _sequences(mappings: str) -> set[str]:
    return {m["sequence"] for m in json.loads(mappings)}


def _check_merge(cur: Any, revision: Revision, removed: tuple[Any, ...]) -> None:
    """The removed description (publication, method, interactors, mappings) is in its survivor."""
    cur.execute(LIVE_DESCRIPTION, (revision.into,))
    survivor = cur.fetchone()
    if survivor is None:
        raise InvalidRow(f"{revision.into}, the survivor, has no live version")
    association_id, method_id, accession1, _, accession2, _, start2, stop2, m1, m2 = survivor
    if removed[:6] != (association_id, method_id, accession1, accession2, start2, stop2):
        raise InvalidRow(
            f"{revision.stable_id} and {revision.into} differ in publication, method or "
            "interactors: not duplicates"
        )
    for side, mine, theirs in ((1, removed[6], m1), (2, removed[7], m2)):
        if missing := mine - _sequences(theirs):
            raise InvalidRow(
                f"{revision.into} lacks the mapping sequences of {revision.stable_id} "
                f"on side {side}: {sorted(missing)}"
            )


def _revise(cur: Any, revision: Revision) -> str | None:
    live_id, version, association = _live(cur, revision)
    cur.execute(LIVE_DESCRIPTION, (revision.stable_id,))
    _, method_id, a1, id1, a2, id2, start2, stop2, mappings1, mappings2 = cur.fetchone()
    kept = ((a1, id1), (a2, id2))
    item = revision.description
    note = revision.note.strip()

    if revision.action == "remove":
        if revision.into:
            # The removed description, as it is or as it was decided to be, is its survivor.
            if item is None:
                removed = (association.id, method_id, a1, a2, start2, stop2)
                removed += (_sequences(mappings1), _sequences(mappings2))
            else:
                row = _build(cur, association, item, kept)
                removed = (association.id, row["method_id"], item.accession1, item.accession2)
                removed += (row["start2"], row["stop2"])
                removed += (_sequences(row["mapping1"]), _sequences(row["mapping2"]))
            _check_merge(cur, revision, removed)
        elif item is not None:
            raise InvalidRow("a removal without `into` takes no description")
        # The live version is deleted, its note gets the REMOVED line.
        cur.execute(
            "UPDATE descriptions SET deleted_at = now(), "
            "annotation = concat_ws(E'\\n', nullif(annotation, ''), nullif(%s::text, '')) "
            "WHERE id = %s",
            (note, live_id),
        )
        return revision.stable_id

    if item is None:
        raise InvalidRow(f"{revision.stable_id}: a revision needs its description")
    row = _build(cur, association, item, kept)
    cur.execute(COLUMNS, (live_id,))
    old = dict(zip(row, cur.fetchone(), strict=True))  # same order; JSON columns come parsed
    new = {**row, "mapping1": json.loads(row["mapping1"]), "mapping2": json.loads(row["mapping2"])}
    if old == new:
        if len(new["mapping1"]) + len(new["mapping2"]) < len(item.mappings1 + item.mappings2):
            return None  # it changes only mappings `_build` skips
        raise InvalidRow(f"the revision of {revision.stable_id} changes nothing")
    cur.execute("UPDATE descriptions SET deleted_at = now() WHERE id = %s", (live_id,))
    _insert(cur, revision.stable_id, version + 1, row, note)
    return revision.stable_id


def live_revisions(cur: Any, pmid: int) -> list[Revision]:
    """The live descriptions of a publication in its vh run, each as a `revise` row to edit
    (empty note).

    Accessions are those of the snapshots used, even obsolete: a revision keeps them unless the
    accession changes.
    """
    association = vh_association(cur, pmid)
    cur.execute(
        """
        SELECT d.stable_id, d.version, m.psimi_id, p1.accession, p2.accession, d.name2, d.start2,
               d.stop2, d.mapping1::text, d.mapping2::text
        FROM descriptions AS d
        JOIN methods AS m ON m.id = d.method_id
        JOIN proteins AS p1 ON p1.id = d.protein1_id
        JOIN proteins AS p2 ON p2.id = d.protein2_id
        WHERE d.association_id = %s AND d.deleted_at IS NULL
        ORDER BY d.stable_id
        """,
        (association.id,),
    )
    revisions: list[Revision] = []
    for stable_id, version, method, a1, a2, name2, start2, stop2, m1, m2 in cur:
        mappings = [cast(list[dict[str, Any]], json.loads(m)) for m in (m1, m2)]
        description = Description(
            method=method,
            accession1=a1,
            accession2=a2,
            name2=name2,
            start2=start2,
            stop2=stop2,
            mappings1=tuple(written(m) for m in mappings[0]),
            mappings2=tuple(written(m) for m in mappings[1]),
        )
        revisions.append(Revision(stable_id, version, pmid, "revise", description))
    return revisions


def revise_descriptions(
    conn: psycopg.Connection, revisions: Sequence[Revision], *, commit: bool = False
) -> Outcome:
    """Revise or remove live descriptions; a stable ID appears once.

    Revisions are applied before removals, so that a duplicate is compared with its survivor
    as revised.
    """
    return write_batch(conn, revisions, [], [], commit=commit)


def _once(revisions: Sequence[Revision]) -> None:
    """Raise `ValueError` for a stable ID given twice."""
    seen: dict[str, int] = {}
    for number, revision in enumerate(revisions, 1):
        if revision.stable_id in seen:
            raise ValueError(
                f"rows {seen[revision.stable_id]} and {number}: {revision.stable_id} twice"
            )
        seen[revision.stable_id] = number


def _removal(revision: Revision) -> bool:
    return revision.action == "remove"


# --- Publications -------------------------------------------------------------------------------

# A new note goes first in the note of a publication, the previous notes after a line `---`.
NEW_NOTE = "concat_ws(E'\\n---\\n', nullif(%s::text, ''), nullif(annotation, ''))"


def _publication(cur: Any, update: PublicationUpdate, author: str = "") -> str:
    association = _writable(vh_association(cur, update.pmid))
    cur.execute(
        f"UPDATE associations SET state = %s, annotation = {NEW_NOTE}, ai_pass_at = now(), "
        "updated_at = now() WHERE id = %s",
        (update.state, _dated(cur, update.note, author), association.id),
    )
    return str(update.pmid)


def _dated(cur: Any, note: str, author: str = "") -> str:
    """A publication note as written, after the date of the write and its author, if any:
    `[2026-10-22] CURATED …`, `[2026-10-22, pmall] CURATED …`."""
    cur.execute("SELECT current_date::text")
    header = ", ".join(part for part in (cur.fetchone()[0], author.strip()) if part)
    return f"[{header}] {note.strip()}"


def update_publications(
    conn: psycopg.Connection,
    updates: Sequence[PublicationUpdate],
    *,
    author: str = "",
    commit: bool = False,
) -> Outcome:
    """Set the state of publications of vh runs at the end of a pass (`ai_pass_at`), the note of
    the pass, after its date and its author (optional), first in their notes."""
    return write_batch(conn, [], [], updates, author=author, commit=commit)


# --- A batch ------------------------------------------------------------------------------------


def write_batch(
    conn: psycopg.Connection,
    revisions: Sequence[Revision],
    additions: Sequence[NewDescription],
    updates: Sequence[PublicationUpdate],
    *,
    author: str = "",
    commit: bool = False,
) -> Outcome:
    """Write a batch in one transaction, in this order: the revisions and removals, the new
    descriptions, the publication updates, their notes after their date and their author
    (optional). Every invariant is checked once, on the result, so a row can rely on an earlier
    one (an addition on a rename).

    Rows are numbered across the three lists, in that order.
    """
    _once(revisions)

    def publication(cur: Any, update: PublicationUpdate) -> str:
        return _publication(cur, update, author)

    def apply(cur: Any) -> Applied:
        stages = [
            _apply_rows(cur, revisions, _revise, order=_removal),
            _apply_rows(cur, additions, _add, len(revisions) + 1),
            _apply_rows(cur, updates, publication, len(revisions) + len(additions) + 1),
        ]
        return [w for s in stages for w in s[0]], [p for s in stages for p in s[1]]

    return _write(conn, commit, apply)
