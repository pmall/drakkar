"""The derived datasets (`docs/datasets.md`), exported from Drakkar (read-only on the
database).

    uv run database-export <generic> <dir> [--run <id>]

Writes the five datasets to the directory, from the live descriptions whose human interactors are
on their current snapshots, in Swiss-Prot: of the vh runs up to `--run`, all by default; of every
hh run. A run is given by its ID (`runs.id`), not its name, so that an export can stop before a
run in progress; a cut that is not the ID of a vh run is refused. The species and generic viral
proteins are read from `<generic>`, the directory of their files (`generic.py`), in step with
Drakkar: a taxon under no species, a species not in `species.tsv` or a name with no protein is
reported, and nothing is written.

Each dataset is written as a `.tsv` file, tab-separated under a header line, and an `.xlsx` file,
the same lines; each name ends with `run` and the name of the last vh run exported by ID, each
character other than a letter, a digit or `-` made a `-`
(`descriptions_vh_run87.tsv`):

- `descriptions_hh`: `stable_id`, `version`, `pmid`, `psimi_id`, `method`; each human interactor:
  `release1` (the release its snapshot first appeared in), `accession1`, `gene_name1`, then
  `release2`, `accession2`, `gene_name2`. One line per description, sorted by stable ID.
- `descriptions_vh`: `stable_id`, `version`, `pmid`, `psimi_id`, `method`; the human interactor:
  `release1` (the release its snapshot first appeared in), `accession1`, `gene_name1`; the viral
  interactor, on any snapshot, from the most general to the most specific:
  `species_ncbi_taxon_id`, `species`, `protein` (from `<generic>`), `strain_ncbi_taxon_id`,
  `strain` (its scientific name, empty when the taxon is missing from the NCBI taxonomy),
  `release2`, `accession2`, `uniprot_name2` (the UniProt protein name), `generic_name2`,
  `start2`, `stop2`. One line per description, sorted by stable ID.
- `interactors_viral`: `release`, `accession`, `start`, `stop`, `sequence` (the canonical
  sequence from start to stop): one line per viral interactor of `descriptions_vh` (`release2`,
  `accession2`, `start2`, `stop2`), sorted by its columns. The snapshot of an entry gone from
  UniProt can be read nowhere else.
- `mappings_h`: `stable_id`, `sequence` (as the experiment used it, its extra end residues
  included, in lowercase: `mSTNPK`), the interactor: `release`, `accession`; `isoform` (the
  isoform it is found on: the canonical one, the accession, when the mapping occurs on it, else
  its other isoform with the lowest number), `target` (`h` or `v`, the kind of the other
  interactor), `nter`, `cter` (the extra end residues, mostly empty). The mappings of the human
  interactors of `descriptions_hh` (both sides) and `descriptions_vh`, one line per (stable ID,
  sequence, isoform): a homodimer's mapping on both sides is one line. Sorted by its columns.
- `mappings_v`: `stable_id`, `sequence`, the interactor: `release`, `accession`, `start`, `stop`;
  `isoform`, `nter`, `cter`, as in `mappings_h`: the mappings of the viral interactors of
  `descriptions_vh`. Sorted by its columns.

Prints the runs exported and the lines of each dataset, then checks the `.tsv` files, read back
(`check_export`): each description on one line in one file; the viral interactors of
`descriptions_vh`, each on one line of `interactors_viral`, its sequence as long as its
coordinates; each mapping on one line, on an interactor of its description, in the file of its
target; and the numbers, each from its own query: the live descriptions of the runs exported,
those exported and those left out (a human interactor not up to date); the mappings of the
descriptions exported, the lines written and those merged in homodimers. It ends with `ok`, or
with the failures and an error, the files left for a look.
"""

import argparse
import csv
import re
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from database.align import written
from database.db import connect
from database.generic import proteins_of
from database.read import taxon_names

VH = [
    "stable_id",
    "version",
    "pmid",
    "psimi_id",
    "method",
    "release1",
    "accession1",
    "gene_name1",
    "species_ncbi_taxon_id",
    "species",
    "protein",
    "strain_ncbi_taxon_id",
    "strain",
    "release2",
    "accession2",
    "uniprot_name2",
    "generic_name2",
    "start2",
    "stop2",
]
HH = [
    "stable_id",
    "version",
    "pmid",
    "psimi_id",
    "method",
    "release1",
    "accession1",
    "gene_name1",
    "release2",
    "accession2",
    "gene_name2",
]
INTERACTORS = ["release", "accession", "start", "stop", "sequence"]
MAPPINGS_H = ["stable_id", "sequence", "release", "accession", "isoform", "target", "nter", "cter"]
MAPPINGS_V = [
    "stable_id",
    "sequence",
    "release",
    "accession",
    "start",
    "stop",
    "isoform",
    "nter",
    "cter",
]


def _write(directory: Path, name: str, columns: list[str], rows: list[list[Any]]) -> None:
    """`<name>.tsv` and `<name>.xlsx` of the directory: the same lines, under the header."""
    with (directory / f"{name}.tsv").open("w", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(name)
    sheet.freeze_panes = "A2"
    sheet.append(columns)
    for row in rows:
        sheet.append(row)
    workbook.save(directory / f"{name}.xlsx")


def _isoform(accession: str, mapping: dict[str, Any]) -> str:
    """The isoform a mapping of the entry is shown on: the canonical one, its accession, when the
    mapping occurs on it, else the other isoform with the lowest number (`-2` before `-10`)."""
    isoforms = [isoform["accession"] for isoform in mapping["isoforms"]]
    if accession in isoforms:
        return accession
    return min(isoforms, key=lambda isoform: int(isoform.rsplit("-", 1)[1]))


def _runs(cur: Any, run: int | None) -> list[int]:
    """The IDs of the vh runs exported: those up to `run`, all when None. A cut that is not the ID
    of a vh run is refused."""
    cur.execute("SELECT id FROM runs WHERE type = 'vh' ORDER BY id")
    runs: list[int] = [i for (i,) in cur.fetchall()]
    if run is not None and run not in runs:
        raise SystemExit(f"--run {run}: not the ID of a vh run")
    return [i for i in runs if run is None or i <= run]


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def check_export(
    cur: Any, directory: Path, top: str, runs: list[int]
) -> tuple[list[str], list[str]]:
    """The `.tsv` files of an export, read back, checked against each other and against the
    database: the numbers, then the failures. `runs` are the IDs of the vh runs exported."""
    hh = _read(directory / f"descriptions_hh_{top}.tsv")
    vh = _read(directory / f"descriptions_vh_{top}.tsv")
    interactors = _read(directory / f"interactors_viral_{top}.tsv")
    mappings_h = _read(directory / f"mappings_h_{top}.tsv")
    mappings_v = _read(directory / f"mappings_v_{top}.tsv")
    failures: list[str] = []

    # each stable ID on one line, in one of the descriptions files
    lines: dict[str, int] = {}
    for row in hh + vh:
        lines[row["stable_id"]] = lines.get(row["stable_id"], 0) + 1
    failures += [f"description on {n} lines: {i}" for i, n in lines.items() if n > 1]
    descriptions = {"h": {r["stable_id"]: r for r in hh}, "v": {r["stable_id"]: r for r in vh}}

    # the viral interactors of descriptions_vh, each on one line, its sequence as long as its
    # coordinates
    used = {(r["release2"], r["accession2"], r["start2"], r["stop2"]) for r in vh}
    written: set[tuple[str, str, str, str]] = set()
    for r in interactors:
        key = (r["release"], r["accession"], r["start"], r["stop"])
        if key in written:
            failures.append(f"viral interactor on several lines: {' '.join(key)}")
        written.add(key)
        if len(r["sequence"]) != int(r["stop"]) - int(r["start"]) + 1:
            failures.append(f"sequence not as long as its coordinates: {' '.join(key)}")
    for k in sorted(used - written):
        failures.append(f"viral interactor without its line: {' '.join(k)}")
    for k in sorted(written - used):
        failures.append(f"viral interactor of no description: {' '.join(k)}")

    # each mapping on one line, on an interactor of its description, in the file of its target
    checked = [(line, "mappings_h", line["target"]) for line in mappings_h]
    checked += [(line, "mappings_v", "v") for line in mappings_v]
    keys: set[tuple[str, str, str, str]] = set()
    for line, name, target in checked:
        key = (name, line["stable_id"], line["sequence"], line["isoform"])
        if key in keys:
            failures.append(f"{name}: mapping on several lines: {' '.join(key[1:])}")
        keys.add(key)
        description = descriptions.get(target, {}).get(line["stable_id"])
        if description is None:
            failures.append(f"{name}: {line['stable_id']} not in descriptions_{target}h")
            continue
        if name == "mappings_v":
            interactor = (line["release"], line["accession"], line["start"], line["stop"])
            own = [tuple(description[c] for c in ("release2", "accession2", "start2", "stop2"))]
        else:
            interactor = (line["release"], line["accession"])
            sides = (1, 2) if target == "h" else (1,)
            own = [(description[f"release{s}"], description[f"accession{s}"]) for s in sides]
        if interactor not in own:
            failures.append(
                f"{name}: {' '.join(interactor)} not an interactor of {line['stable_id']}"
            )
        if not re.fullmatch(re.escape(line["accession"]) + r"(-\d+)?", line["isoform"]):
            failures.append(f"{name}: isoform {line['isoform']} not of {line['accession']}")

    # the numbers, each from its own query: the live descriptions of the runs exported, those
    # left out (a human interactor not up to date); the mappings of the descriptions exported,
    # those merged (the same sequence on both sides of a homodimer)
    cur.execute(
        """
        WITH live AS (
            SELECT r.type,
                   c1.reviewed IS TRUE AND (r.type = 'vh' OR c2.reviewed IS TRUE) AS exported,
                   json_array_length(d.mapping1) + json_array_length(d.mapping2) AS mappings,
                   CASE WHEN d.protein1_id = d.protein2_id THEN (
                       SELECT count(*)
                       FROM json_array_elements(d.mapping1) AS m1
                       JOIN json_array_elements(d.mapping2) AS m2
                         ON m2.value ->> 'sequence' = m1.value ->> 'sequence'
                   ) ELSE 0 END AS merged
            FROM descriptions AS d
            JOIN associations AS a ON a.id = d.association_id
            JOIN runs AS r ON r.id = a.run_id
            JOIN proteins AS p1 ON p1.id = d.protein1_id
            LEFT JOIN proteins_versions AS c1
              ON c1.accession = p1.accession AND c1.version = p1.version
            JOIN proteins AS p2 ON p2.id = d.protein2_id
            LEFT JOIN proteins_versions AS c2
              ON c2.accession = p2.accession AND c2.version = p2.version
            WHERE d.deleted_at IS NULL AND (r.type = 'hh' OR a.run_id = ANY(%s))
        )
        SELECT type,
               count(*) AS live,
               count(*) FILTER (WHERE NOT exported) AS left_out,
               coalesce(sum(mappings) FILTER (WHERE exported), 0) AS mappings,
               coalesce(sum(merged) FILTER (WHERE exported), 0) AS merged
        FROM live
        GROUP BY type
        """,
        (runs,),
    )
    counts = {kind: (live, left, m, merged) for kind, live, left, m, merged in cur.fetchall()}
    numbers: list[str] = []
    for kind, rows in (("vh", vh), ("hh", hh)):
        live, left_out, _, _ = counts.get(kind, (0, 0, 0, 0))
        sign = "=" if live == len(rows) + left_out else "≠"
        numbers.append(
            f"{kind} descriptions: {live} live {sign} {len(rows)} exported + {left_out} left out "
            "(a human interactor not up to date)"
        )
        if sign == "≠":
            failures.append(f"{kind} descriptions: the numbers do not add up")
    total = sum(m for _, _, m, _ in counts.values())
    merged = sum(m for _, _, _, m in counts.values())
    written_lines = len(mappings_h) + len(mappings_v)
    sign = "=" if total == written_lines + merged else "≠"
    numbers.append(
        f"mappings: {total} on the descriptions exported {sign} {written_lines} lines "
        f"+ {merged} merged (the same sequence on both sides of a homodimer)"
    )
    if sign == "≠":
        failures.append("mappings: the numbers do not add up")
    return numbers, failures


def export(
    cur: Any,
    generic: Path,
    directory: Path,
    run: int | None = None,
) -> str:
    """Write the five datasets to the directory; the report: what each holds."""
    runs = _runs(cur, run)
    cur.execute(
        """
        SELECT d.stable_id, d.version, a.pmid, m.psimi_id, m.name AS method,
               h.version AS release1, h.accession AS accession1, h.name AS gene_name1,
               v.id AS protein2_id, v.ncbi_taxon_id AS strain_ncbi_taxon_id,
               v.version AS release2, v.accession AS accession2, v.description AS uniprot_name2,
               d.name2 AS generic_name2, d.start2, d.stop2, d.mapping1, d.mapping2
        FROM descriptions AS d
        JOIN associations AS a ON a.id = d.association_id
        JOIN methods AS m ON m.id = d.method_id
        JOIN proteins AS h ON h.id = d.protein1_id
        JOIN proteins_versions AS current1
          ON current1.accession = h.accession AND current1.version = h.version
        JOIN proteins AS v ON v.id = d.protein2_id
        WHERE d.deleted_at IS NULL AND a.run_id = ANY(%s) AND current1.reviewed
        ORDER BY d.stable_id
        """,
        (runs,),
    )
    columns = [c.name for c in cur.description]
    vh = [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]

    proteins, missing = proteins_of(
        cur, generic, {(row["strain_ncbi_taxon_id"], row["generic_name2"]) for row in vh}
    )
    if missing:
        raise SystemExit(
            f"{generic} is not in step with the descriptions exported, nothing written: "
            "the export skill brings it in step (database-generic sync)\n" + "\n".join(missing)
        )
    # a taxon missing from NCBI has no name
    strains = taxon_names(cur, {row["strain_ncbi_taxon_id"] for row in vh})
    for row in vh:
        taxon = row["strain_ncbi_taxon_id"]
        row["species_ncbi_taxon_id"], row["species"], row["protein"] = proteins[
            (taxon, row["generic_name2"])
        ]
        row["strain"] = strains.get(taxon, "")

    # each viral interactor, (release, accession, start, stop), and its snapshot
    interactors = {
        (row["release2"], row["accession2"], row["start2"], row["stop2"]): row["protein2_id"]
        for row in vh
    }
    cur.execute(
        "SELECT id, sequences ->> accession AS sequence FROM proteins WHERE id = ANY(%s)",
        (list(set(interactors.values())),),
    )
    sequences: dict[int, str] = dict(cur.fetchall())

    cur.execute(
        """
        SELECT d.stable_id, d.version, a.pmid, m.psimi_id, m.name AS method,
               h1.version AS release1, h1.accession AS accession1, h1.name AS gene_name1,
               h2.version AS release2, h2.accession AS accession2, h2.name AS gene_name2,
               d.mapping1, d.mapping2
        FROM descriptions AS d
        JOIN associations AS a ON a.id = d.association_id
        JOIN runs AS r ON r.id = a.run_id
        JOIN methods AS m ON m.id = d.method_id
        JOIN proteins AS h1 ON h1.id = d.protein1_id
        JOIN proteins_versions AS current1
          ON current1.accession = h1.accession AND current1.version = h1.version
        JOIN proteins AS h2 ON h2.id = d.protein2_id
        JOIN proteins_versions AS current2
          ON current2.accession = h2.accession AND current2.version = h2.version
        WHERE d.deleted_at IS NULL AND r.type = 'hh' AND current1.reviewed AND current2.reviewed
        ORDER BY d.stable_id
        """
    )
    columns = [c.name for c in cur.description]
    hh = [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]

    # each side of a description: its interactor's kind, the other interactor's kind (target)
    sides = [(row, 1, "h", "v") for row in vh] + [(row, 2, "v", "h") for row in vh]
    sides += [(row, side, "h", "h") for row in hh for side in (1, 2)]
    # one line per (stable ID, sequence, isoform): a homodimer's mapping on both sides is one
    mappings: dict[str, dict[tuple[str, str, str], list[Any]]] = {"h": {}, "v": {}}
    for row, side, kind, target in sides:
        release, accession = row[f"release{side}"], row[f"accession{side}"]
        for mapping in row[f"mapping{side}"]:
            nter, cter = mapping.get("nter", ""), mapping.get("cter", "")
            sequence = written(mapping)  # as in the files: mSTNPK
            isoform = _isoform(accession, mapping)
            line = [row["stable_id"], sequence, release, accession]
            if kind == "h":
                line += [isoform, target, nter, cter]
            else:
                line += [row["start2"], row["stop2"], isoform, nter, cter]
            mappings[kind].setdefault((row["stable_id"], sequence, isoform), line)

    cur.execute(
        "SELECT name FROM runs WHERE id = %s",
        (max(runs),),
    )
    (name,) = cur.fetchone()
    top = "run" + re.sub(r"[^A-Za-z0-9-]", "-", name)  # in a file name, `_` separates its parts
    directory.mkdir(parents=True, exist_ok=True)
    _write(directory, f"descriptions_hh_{top}", HH, [[row[c] for c in HH] for row in hh])
    _write(directory, f"descriptions_vh_{top}", VH, [[row[c] for c in VH] for row in vh])
    _write(
        directory,
        f"interactors_viral_{top}",
        INTERACTORS,
        [
            [release, accession, start, stop, sequences[i][start - 1 : stop]]
            for (release, accession, start, stop), i in sorted(interactors.items())
        ],
    )
    _write(directory, f"mappings_h_{top}", MAPPINGS_H, sorted(mappings["h"].values()))
    _write(directory, f"mappings_v_{top}", MAPPINGS_V, sorted(mappings["v"].values()))

    report = [
        f"vh runs: {len(runs)}, {'all' if run is None else f'up to ID {run}'}",
        f"descriptions_hh_{top} (.tsv, .xlsx): {len(hh)} descriptions",
        f"descriptions_vh_{top} (.tsv, .xlsx): {len(vh)} descriptions",
        f"interactors_viral_{top} (.tsv, .xlsx): {len(interactors)} viral interactors",
        f"mappings_h_{top} (.tsv, .xlsx): {len(mappings['h'])} mappings",
        f"mappings_v_{top} (.tsv, .xlsx): {len(mappings['v'])} mappings",
        "check:",
    ]
    numbers, failures = check_export(cur, directory, top, runs)
    report += [f"  {line}" for line in numbers]
    if not failures:
        return "\n".join([*report, "  ok"])
    report.append(f"  {len(failures)} failures:")
    report += [f"  {line}" for line in failures[:20]]
    if len(failures) > 20:
        report.append(f"  … {len(failures) - 20} more")
    raise SystemExit("\n".join(report))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("generic", type=Path)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--run", type=int)
    args = parser.parse_args()
    with connect(readonly=True) as conn, conn.cursor() as cur:
        cur.execute("SET statement_timeout = '60s'")
        print(export(cur, args.generic, args.directory, args.run))
