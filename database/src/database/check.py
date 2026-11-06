"""The Drakkar invariants (`docs/database.md#invariants`) on vh and hh data, checked without
writing: each invariant is a query returning its violations, one row per violation, with the
stable ID and PMID when relevant. `run` writes the report of `database/scripts/check.py`.
"""

import csv
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, LiteralString, cast

import psycopg

from database.align import MIN_IDENTITY, core, segment_identity
from database.db import require_idle

Rows = tuple[list[str], list[tuple[Any, ...]]]

# The snapshots used by live descriptions, each read once.
SNAPSHOT_IDS = """
    CREATE TEMP TABLE snap_ids AS
    SELECT protein1_id AS id FROM descriptions WHERE deleted_at IS NULL
    UNION SELECT protein2_id FROM descriptions WHERE deleted_at IS NULL
"""
SNAPSHOTS = """
    CREATE TEMP TABLE snap AS
    SELECT p.id, p.accession, p.type, p.name AS gene, p.ncbi_taxon_id AS taxon,
           length(p.sequences->>p.accession) AS length,
           v.accession IS NOT NULL AS current
    FROM proteins AS p
    JOIN snap_ids USING (id)
    LEFT JOIN proteins_versions AS v ON v.accession = p.accession AND v.version = p.version
"""

# Live descriptions (vh and hh) with everything needed by the checks.
LIVE = """
    CREATE TEMP TABLE live AS
    SELECT d.*, r.type AS run_type, a.pmid, a.state, r.name AS run,
           s1.accession AS accession1, s1.type AS type1, s1.gene AS gene1,
           s1.taxon AS taxon1, s1.length AS length1,
           s2.accession AS accession2, s2.type AS type2, s2.gene AS gene2,
           s2.taxon AS taxon2, s2.length AS length2,
           s1.current AS current1, s2.current AS current2,
           m.psimi_id
    FROM descriptions AS d
    JOIN associations AS a ON a.id = d.association_id
    JOIN runs AS r ON r.id = a.run_id
    JOIN methods AS m ON m.id = d.method_id
    JOIN snap AS s1 ON s1.id = d.protein1_id
    JOIN snap AS s2 ON s2.id = d.protein2_id
    WHERE d.deleted_at IS NULL
"""

# All description rows (live and deleted), for the versioning checks.
VERSIONS = """
    CREATE TEMP TABLE versions AS
    SELECT d.*, r.type AS run_type, a.pmid FROM descriptions AS d
    JOIN associations AS a ON a.id = d.association_id
    JOIN runs AS r ON r.id = a.run_id
"""

# Each side of each live description, as one row: the checks that look at a side read this.
SIDES = """
    CREATE TEMP VIEW sides AS
    SELECT run_type, stable_id, pmid, 1 AS side, protein1_id AS protein_id, type1 AS type,
           accession1 AS accession, taxon1 AS taxon, current1 AS current, name1 AS name,
           gene1 AS gene, start1 AS start, stop1 AS stop, length1 AS length, mapping1 AS mapping
    FROM live
    UNION ALL
    SELECT run_type, stable_id, pmid, 2, protein2_id, type2, accession2, taxon2, current2, name2,
           gene2, start2, stop2, length2, mapping2
    FROM live
"""

TEMP_TABLES = """
    DROP VIEW IF EXISTS pg_temp.sides;
    DROP TABLE IF EXISTS pg_temp.snap_ids, pg_temp.snap, pg_temp.live, pg_temp.versions
"""


@dataclass
class Invariant:
    id: str
    severity: str  # "error", "warning", "upgrade" (an obsolete snapshot) or "info"
    title: str
    check: LiteralString | Callable[[Any], Rows]


SQL_INVARIANTS = [
    Invariant(
        "R3",
        "info",
        "Proteins of live descriptions whose taxon is not in `taxon` (UniProt ahead of NCBI).",
        """
        SELECT run_type, stable_id, pmid, side, accession, taxon FROM sides
        WHERE NOT EXISTS (SELECT 1 FROM taxon WHERE taxon.ncbi_taxon_id = sides.taxon)
        ORDER BY accession, stable_id
        """,
    ),
    Invariant(
        "V2",
        "error",
        "Versions of a stable ID are contiguous from 1.",
        """
        SELECT min(run_type) AS run_type, stable_id, min(version) AS min, max(version) AS max,
               count(*) AS versions
        FROM versions GROUP BY stable_id
        HAVING min(version) <> 1 OR max(version) <> count(*)
        ORDER BY stable_id
        """,
    ),
    Invariant(
        "V3",
        "error",
        "At most one live row per stable ID, and it is the highest version.",
        """
        SELECT min(run_type) AS run_type, stable_id,
               count(*) FILTER (WHERE deleted_at IS NULL) AS live_rows,
               max(version) AS max_version,
               max(version) FILTER (WHERE deleted_at IS NULL) AS live_version
        FROM versions GROUP BY stable_id
        HAVING count(*) FILTER (WHERE deleted_at IS NULL) > 1
            OR max(version) FILTER (WHERE deleted_at IS NULL) <> max(version)
        ORDER BY stable_id
        """,
    ),
    Invariant(
        "V4",
        "error",
        "Each non-last version is deleted, no later than the next version's creation.",
        """
        SELECT v.run_type, v.stable_id, v.version, v.deleted_at,
               next.created_at AS next_created_at
        FROM versions AS v
        JOIN versions AS next ON next.stable_id = v.stable_id AND next.version = v.version + 1
        WHERE v.deleted_at IS NULL OR v.deleted_at > next.created_at
        ORDER BY v.stable_id, v.version
        """,
    ),
    Invariant(
        "V5",
        "error",
        "`deleted_at` is not before `created_at`.",
        """
        SELECT run_type, stable_id, version, created_at, deleted_at FROM versions
        WHERE deleted_at < created_at ORDER BY stable_id, version
        """,
    ),
    Invariant(
        "V6",
        "error",
        "All versions of a stable ID belong to the same publication.",
        """
        SELECT min(run_type) AS run_type, stable_id,
               count(DISTINCT association_id) AS associations FROM versions
        GROUP BY stable_id HAVING count(DISTINCT association_id) > 1 ORDER BY stable_id
        """,
    ),
    Invariant(
        "V7",
        "error",
        "Stable ID format: `EY` or `CW` + 8 uppercase hexadecimal characters (legacy hh bulk "
        "import: `EYUW` + 6 hexadecimal characters).",
        """
        SELECT DISTINCT run_type, stable_id FROM versions
        WHERE stable_id !~ '^((EY|CW)[0-9A-F]{8}|EYUW[0-9A-F]{6})$' ORDER BY stable_id
        """,
    ),
    Invariant(
        "D1",
        "error",
        "Protein 1 is human; protein 2 is viral in vh runs, human in hh runs.",
        """
        SELECT run_type, stable_id, pmid, accession1, type1, accession2, type2 FROM live
        WHERE type1 <> 'h' OR type2 <> (CASE run_type WHEN 'vh' THEN 'v' ELSE 'h' END)
        ORDER BY pmid, stable_id
        """,
    ),
    Invariant(
        "D2",
        "upgrade",
        "Both proteins are current snapshots (latest UniProt release).",
        """
        SELECT run_type, stable_id, pmid, side, accession FROM sides
        WHERE NOT current ORDER BY accession, stable_id, side
        """,
    ),
    Invariant(
        "D3",
        "error",
        "Viral interactors: 1 ≤ start ≤ stop ≤ canonical length (human ones: D4).",
        """
        SELECT run_type, stable_id, pmid, 2 AS side, accession2 AS accession,
               start2 AS start, stop2 AS stop, length2 AS length FROM live
        WHERE type2 = 'v' AND (start2 < 1 OR start2 > stop2 OR stop2 > length2)
        ORDER BY accession, stable_id
        """,
    ),
    Invariant(
        "D4",
        "error",
        "Human interactors are the full protein (start = 1, stop = canonical length).",
        """
        SELECT run_type, stable_id, pmid, side, accession, start, stop, length FROM sides
        WHERE (side = 1 OR type = 'h') AND (start <> 1 OR stop <> length)
        ORDER BY accession, stable_id
        """,
    ),
    Invariant(
        "D5",
        "error",
        "One live description per (publication, method, interactor 1, interactor 2).",
        """
        SELECT run_type, pmid, psimi_id, accession1, start1, stop1, accession2, start2, stop2,
               count(*) AS descriptions, string_agg(stable_id, ' ' ORDER BY stable_id) AS stable_ids
        FROM live
        GROUP BY run_type, association_id, pmid, psimi_id, accession1, start1, stop1,
                 accession2, start2, stop2
        HAVING count(*) > 1
        ORDER BY pmid, accession1, accession2
        """,
    ),
    Invariant(
        "D6",
        "error",
        "One non-empty generic name (`name2`) per viral interactor (accession, start, stop).",
        """
        SELECT run_type, accession2, start2, stop2,
               string_agg(DISTINCT name2, ' | ') AS names, count(*) AS descriptions,
               string_agg(stable_id, ' ' ORDER BY stable_id) AS stable_ids
        FROM live WHERE run_type = 'vh'
        GROUP BY run_type, accession2, start2, stop2
        HAVING count(DISTINCT name2) > 1 OR bool_or(trim(name2) = '')
        ORDER BY accession2, start2
        """,
    ),
    Invariant(
        "D10",
        "error",
        "One viral interactor (start, stop) per generic name of a viral snapshot "
        "(`protein2_id`, `name2`).",
        """
        SELECT run_type, accession2, protein2_id, name2,
               string_agg(DISTINCT start2 || '-' || stop2, ' | ') AS coordinates,
               count(*) AS descriptions,
               string_agg(stable_id, ' ' ORDER BY stable_id) AS stable_ids
        FROM live WHERE run_type = 'vh'
        GROUP BY run_type, accession2, protein2_id, name2
        HAVING count(DISTINCT (start2, stop2)) > 1
        ORDER BY accession2, name2
        """,
    ),
    Invariant(
        "D7",
        "warning",
        "Human names (`name1`, and `name2` in hh) are the gene name of their snapshot.",
        """
        SELECT run_type, stable_id, pmid, side, accession, name, gene FROM sides
        WHERE (side = 1 OR run_type = 'hh') AND name <> gene
        ORDER BY accession, stable_id
        """,
    ),
    Invariant(
        "S1",
        "error",
        "A publication with a live description is `selected` (curation in progress) or `curated`.",
        """
        SELECT run_type, pmid, run, state, count(*) AS descriptions FROM live
        WHERE state NOT IN ('selected', 'curated') GROUP BY run_type, pmid, run, state
        ORDER BY pmid
        """,
    ),
    Invariant(
        "S5",
        "error",
        "Run names are unique.",
        "SELECT name, count(*) FROM runs GROUP BY name HAVING count(*) > 1 ORDER BY name",
    ),
]


AMINO_ACIDS = re.compile(r"[ACDEFGHIKLMNPQRSTVWYUOXBZJ]+")
OCCURRENCE_KEYS = ("start", "stop", "identity")
# How far below its recorded identity an occurrence may align on its segment: legacy gap
# placement, up to 0.47 point.
IDENTITY_TOLERANCE = 1.0
# The threshold legacy descriptions were curated with; `MIN_IDENTITY` applies to those Drakkar's
# writes add (`CW`). Both are warnings (D12), never errors.
LEGACY_MIN_IDENTITY = 96.0
NUMBER = re.compile(r"\d+(\.\d+)?")

# The description sides with mappings, with what the mapping checks need.
MAPPING_SIDES = """
    SELECT s.run_type, s.stable_id, s.pmid, s.side, s.type, s.accession, s.start, s.stop,
           s.mapping::text, p.sequences::text
    FROM sides AS s JOIN proteins AS p ON p.id = s.protein_id
    WHERE s.mapping::jsonb <> '[]'
    ORDER BY s.stable_id, s.side
"""
# The first columns of D9 and D12: the description side of the mapping.
SIDE_COLUMNS = ["run_type", "stable_id", "pmid", "side", "protein", "accession"]


def _number(value: Any, strict: bool) -> float | None:
    """A JSON number as a float; unless `strict`, a number stored as text too; None otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not strict and isinstance(value, str) and NUMBER.fullmatch(value):
        return float(value)
    return None


def mapping_structure(mappings: Any, strict: bool = True) -> list[str]:
    """Structure and type problems of a mapping column (D11), without looking at the content.

    The structure is a list of objects `{"sequence": string, "nter": string, "cter": string,
    "isoforms": [{"accession": string, "occurrences": [{"start": number, "stop": number,
    "identity": number}]}]}`, `nter` and `cter` optional. Unless `strict`, numbers stored as text
    are accepted, so that D9 can read the content.
    """
    if not isinstance(mappings, list):
        return ["not a list of mappings"]
    problems: set[str] = set()
    for mapping in cast(list[Any], mappings):
        if not isinstance(mapping, dict):
            problems.add("a mapping is not an object")
            continue
        fields = cast(dict[str, Any], mapping)
        if not isinstance(fields.get("sequence"), str):
            problems.add("a sequence is not a string")
        for key in ("nter", "cter"):
            if key in fields and not isinstance(fields[key], str):
                problems.add(f"{key} is not a string")
        isoforms = fields.get("isoforms")
        if not isinstance(isoforms, list):
            problems.add("isoforms is not a list")
            continue
        for isoform in cast(list[Any], isoforms):
            if not isinstance(isoform, dict):
                problems.add("an isoform is not an object")
                continue
            entry = cast(dict[str, Any], isoform)
            if not isinstance(entry.get("accession"), str):
                problems.add("an isoform accession is not a string")
            occurrences = entry.get("occurrences")
            if not isinstance(occurrences, list):
                problems.add("occurrences is not a list")
                continue
            for occurrence in cast(list[Any], occurrences):
                if not isinstance(occurrence, dict):
                    problems.add("an occurrence is not an object")
                    continue
                values = cast(dict[str, Any], occurrence)
                for key in OCCURRENCE_KEYS:
                    if _number(values.get(key), strict) is not None:
                        continue
                    if _number(values.get(key), strict=False) is not None:
                        problems.add("numbers stored as text")
                    else:
                        problems.add(f"an occurrence {key} is not a number")
    return sorted(problems)


def _misfit(
    mapping: dict[str, Any],
    isoforms: dict[str, str],
    accession: str,
    start: int,
    stop: int,
) -> str:
    """Why the occurrences of a mapping do not fit the sequences of its snapshot, or "".

    Each stored occurrence is judged on its own, against the protein segment at its coordinates:
    the mapping is located without its `nter` and `cter`. An occurrence recorded at 100 % must be
    exactly the mapping; otherwise the mapping aligned end to end on the segment must be no more
    than `IDENTITY_TOLERANCE` below the recorded identity.
    Low identities are warnings (D12), not misfits. Whether the mapping could also be found
    elsewhere, or on other isoforms, is not checked.
    """
    occurrences = [
        (i["accession"], *(cast(float, _number(o[k], strict=False)) for k in OCCURRENCE_KEYS))
        for i in mapping["isoforms"]
        for o in i["occurrences"]
    ]
    if not occurrences:
        return "no occurrence"
    for isoform, first, last, stored in occurrences:
        sequence = isoforms.get(isoform)
        if sequence is None:
            return f"isoform {isoform} not in the snapshot"
        if isoform == accession:
            sequence = sequence[start - 1 : stop]
        if not 1 <= first <= last <= len(sequence):
            return f"occurrence {first:g}-{last:g} outside {isoform}"
        segment = sequence[int(first) - 1 : int(last)]
        if stored == 100 and segment != core(mapping):
            return f"100 % occurrence {first:g}-{last:g} does not match {isoform}"
        identity = segment_identity(core(mapping), segment)
        if identity < stored - IDENTITY_TOLERANCE:
            return (
                f"occurrence {first:g}-{last:g} on {isoform} recorded at {stored:g} %, "
                f"{identity:g} % at its coordinates"
            )
    return ""


def _protein(type_: str) -> str:
    return {"h": "human", "v": "viral"}.get(type_, type_)


def check_d9(cur: Any) -> Rows:
    """Mapping content: an amino acid sequence, once, with an occurrence that fits.

    Every stored occurrence must be true to its coordinates (`_misfit`), whatever its identity
    (low identities are D12 warnings). Occurrence positions are relative to the interactor
    region [start, stop] on the canonical isoform, to the whole sequence on other isoforms.
    Mappings whose structure cannot be read are left to D11; numbers stored as text are read as
    numbers. `protein` tells a human mapping from a viral one, which are separate fixes.
    """
    cur.execute(MAPPING_SIDES)
    rows: list[tuple[Any, ...]] = []
    for row in cur.fetchall():
        run_type, stable_id, pmid, side, type_, accession, start, stop, text, sequences = row
        mappings: Any = json.loads(text or "null")
        if mapping_structure(mappings, strict=False):
            continue
        where = (run_type, stable_id, pmid, side, _protein(type_), accession)
        isoforms: dict[str, str] = json.loads(sequences)
        seen: set[str] = set()
        for mapping in mappings:
            sequence = mapping["sequence"]
            problems: list[str] = []
            if not AMINO_ACIDS.fullmatch(sequence):
                problems.append("sequence is not an uppercase amino acid sequence")
            if sequence in seen:
                problems.append("duplicate mapping sequence")
            nter, cter = mapping.get("nter", ""), mapping.get("cter", "")
            ends = sequence.startswith(nter) and sequence.endswith(cter)
            named = "" not in (mapping.get("nter"), mapping.get("cter"))  # when present, not empty
            if not (ends and named and len(nter) + len(cter) < len(sequence)):
                problems.append("nter and cter are not the ends of the sequence")
            seen.add(sequence)
            if misfit := _misfit(mapping, isoforms, accession, start, stop):
                problems.append(misfit)
            if problems:
                rows.append((*where, len(sequence), "; ".join(problems)))
    return [*SIDE_COLUMNS, "mapping_length", "problem"], rows


def check_d12(cur: Any) -> Rows:
    """Mapping identity (warning): the best recorded identity of a mapping is below the threshold.

    `LEGACY_MIN_IDENTITY` (96 %) for `EY` descriptions, `MIN_IDENTITY` (90 %) for `CW` ones.
    """
    cur.execute(MAPPING_SIDES)
    rows: list[tuple[Any, ...]] = []
    for row in cur.fetchall():
        run_type, stable_id, pmid, side, type_, accession, _, _, text, _ = row
        mappings: Any = json.loads(text or "null")
        if mapping_structure(mappings, strict=False):
            continue
        where = (run_type, stable_id, pmid, side, _protein(type_), accession)
        threshold = MIN_IDENTITY if stable_id.startswith("CW") else LEGACY_MIN_IDENTITY
        for mapping in mappings:
            identities = [
                cast(float, _number(o["identity"], strict=False))
                for i in mapping["isoforms"]
                for o in i["occurrences"]
            ]
            if identities and max(identities) < threshold:
                rows.append((*where, len(mapping["sequence"]), max(identities), threshold))
    return [*SIDE_COLUMNS, "mapping_length", "best_identity", "threshold"], rows


def check_d11(cur: Any) -> Rows:
    """Mapping structure: the shape and the types of the JSON, not its content.

    Every version is checked, live or deleted: a structure problem is fixed in place, without a
    revision, in all the rows that have it (`docs/database.md#versioning`). One
    row per version side.
    """
    cur.execute("""
        SELECT v.run_type, v.stable_id, v.version, v.deleted_at IS NULL, v.pmid,
               1 AS side, p.type, p.accession, v.mapping1::text
        FROM versions AS v JOIN proteins AS p ON p.id = v.protein1_id
        WHERE v.mapping1::jsonb <> '[]'
        UNION ALL
        SELECT v.run_type, v.stable_id, v.version, v.deleted_at IS NULL, v.pmid,
               2, p.type, p.accession, v.mapping2::text
        FROM versions AS v JOIN proteins AS p ON p.id = v.protein2_id
        WHERE v.mapping2::jsonb <> '[]'
    """)
    rows: list[tuple[Any, ...]] = []
    for run_type, stable_id, version, live, pmid, side, type_, accession, text in cur.fetchall():
        if problems := mapping_structure(json.loads(text or "null")):
            rows.append(
                (
                    run_type,
                    stable_id,
                    version,
                    "yes" if live else "no",
                    pmid,
                    side,
                    _protein(type_),
                    accession,
                    "; ".join(problems),
                )
            )
    header = [
        "run_type",
        "stable_id",
        "version",
        "live",
        "pmid",
        "side",
        "protein",
        "accession",
        "problem",
    ]
    return header, rows


INVARIANTS = sorted(
    [
        *SQL_INVARIANTS,
        Invariant(
            "D9",
            "error",
            "Mapping content: an amino acid sequence, once per side, its nter and cter at its "
            "ends, with occurrences of the rest true to their coordinates: exact at 100 %, "
            "otherwise within 1 point of the identity at those coordinates.",
            check_d9,
        ),
        Invariant(
            "D12",
            "warning",
            "Mapping identity: the best occurrence of a mapping is below 96 % (EY) or 90 % (CW).",
            check_d12,
        ),
        Invariant(
            "D11",
            "error",
            "Mapping structure, every version: a list of objects with the expected fields "
            "and JSON types (numbers as text are fixed in place).",
            check_d11,
        ),
    ],
    key=lambda i: (i.id[0] != "R", i.id[0] != "V", i.id[0], int(i.id[1:])),
)


@dataclass
class Result:
    invariant: Invariant
    header: list[str]
    rows: list[tuple[Any, ...]]

    def count(self, run_type: str) -> int:
        """Violations in vh or hh runs; a global invariant (runs) counts as vh."""
        if "run_type" not in self.header:
            return len(self.rows) if run_type == "vh" else 0
        column = self.header.index("run_type")
        return sum(1 for row in self.rows if row[column] == run_type)


def run_checks(cur: Any, log: bool = False) -> list[Result]:
    """Check every invariant on the whole database, as this transaction sees it.

    Only temporary tables are created, and they are dropped at the end: the caller's
    transaction can go on, and commit or roll back.
    """
    start = time.time()
    # JIT compilation costs seconds on these plans and saves nothing.
    cur.execute("SELECT current_setting('jit')")
    jit = cur.fetchone()[0]
    cur.execute("SET LOCAL jit = off")
    cur.execute(TEMP_TABLES)
    for sql in (SNAPSHOT_IDS, "ANALYZE snap_ids", SNAPSHOTS, LIVE, VERSIONS, SIDES):
        cur.execute(sql)
    results: list[Result] = []
    for invariant in INVARIANTS:
        if callable(invariant.check):
            header, rows = invariant.check(cur)
        else:
            cur.execute(invariant.check)
            columns: list[Any] = cur.description or []
            header = [str(c.name) for c in columns]
            rows = cur.fetchall()
        results.append(Result(invariant, header, rows))
        if log:
            print(f"[{time.time() - start:6.1f}s] {invariant.id}: {len(rows)}", file=sys.stderr)
    cur.execute(TEMP_TABLES)
    cur.execute("SELECT set_config('jit', %s, true)", (jit,))
    return results


def errors(results: list[Result]) -> list[Result]:
    """The violated invariants of severity error."""
    return [r for r in results if r.invariant.severity == "error" and r.rows]


def summary(results: list[Result]) -> list[str]:
    """Markdown table of the invariants with their violations in vh and hh."""
    lines = ["| ID | Severity | Invariant | vh | hh |", "|---|---|---|---:|---:|"]
    lines += [
        f"| {r.invariant.id} | {r.invariant.severity} | {r.invariant.title} "
        f"| {r.count('vh')} | {r.count('hh')} |"
        for r in results
    ]
    return lines


def run(conn: psycopg.Connection, output: Path) -> tuple[str, bool]:
    """Checks every invariant in a transaction of its own, rolled back, writes the report to the
    directory, and returns its summary and whether no error was found."""
    output.mkdir(parents=True, exist_ok=True)
    require_idle(conn)
    with conn.cursor() as cur:
        results = run_checks(cur, log=True)
        cur.execute(
            """
            SELECT r.type, count(*), count(DISTINCT a.pmid)
            FROM descriptions AS d
            JOIN associations AS a ON a.id = d.association_id
            JOIN runs AS r ON r.id = a.run_id
            WHERE d.deleted_at IS NULL
            GROUP BY r.type
            """
        )
        scope = {t: (n, p) for t, n, p in cur.fetchall()}
        conn.rollback()
    for result in results:
        path = output / f"{result.invariant.id}.tsv"
        if result.rows:
            with path.open("w") as f:
                writer = csv.writer(f, delimiter="\t", lineterminator="\n")
                writer.writerow(result.header)
                writer.writerows(result.rows)
        else:
            path.unlink(missing_ok=True)

    lines = [
        f"# Drakkar check, {date.today()}",
        "",
        "Live descriptions: "
        + ", ".join(f"{t} {n} in {p} publications" for t, (n, p) in sorted(scope.items()))
        + ". One TSV per violated invariant in this directory (rows of the violations).",
        "",
        *summary(results),
    ]
    (output / "check.md").write_text("\n".join(lines) + "\n")
    return "\n".join(lines), not errors(results)
