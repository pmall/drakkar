"""The generic viral proteins of the vh descriptions dataset: the files of their directory kept in
step with Drakkar (read-only on the database).

The vh descriptions dataset is `descriptions_vh` (`export.py`). Its generic viral proteins are
three files, versioned in git in `database/generic/`, tab-separated under a header
line:

- `species.tsv`: `family_ncbi_taxon_id` (empty when the NCBI taxonomy places the taxon in no
  family), `ncbi_taxon_id`, `name` (the virus name readers use, not the NCBI binomial),
  `publications` (the publications of its live vh descriptions): the NCBI taxa each treated as one
  virus, the species, one line each, sorted by family, then species (a species in no family
  last). A person writes `ncbi_taxon_id` and `name`; `sync` fills the others.
- `placed.tsv`: `ncbi_taxon_id`, `species_ncbi_taxon_id`, `name`: a taxon of viral interactors
  placed in its species by a person, with its subtree: one missing from the NCBI taxonomy, or one
  the taxonomy keeps outside the species its virus is (an old species beside its successor, an
  unclassified taxon of a known virus); sorted by species, then taxon.
- `proteins.tsv`: `ncbi_taxon_id` (the species), `generic_name`, `protein`, `note`: one line per
  generic name of the dataset in its species, `protein` the label of the generic viral protein it
  is shown as, `note` why, when it is not obvious; sorted as `species.tsv`, then by name.

The species of a viral interactor is given by the deepest taxon at or above its taxon in
`species.tsv` (that taxon) or `placed.tsv` (the species it is placed in).

`sync` keeps them in step, run by `database/scripts/generic.py`, which describes it.
"""

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

from database import read

SPECIES = ["family_ncbi_taxon_id", "ncbi_taxon_id", "name", "publications"]
PLACED = ["ncbi_taxon_id", "species_ncbi_taxon_id", "name"]
PROTEINS = ["ncbi_taxon_id", "generic_name", "protein", "note"]


def _read(path: Path, columns: list[str]) -> list[dict[str, str]]:
    """The lines of a file, an absent file having none; a header other than `columns` is refused."""
    if not path.exists():
        return []
    with path.open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames != columns:
            raise ValueError(f"{path}: the header must be {' '.join(columns)}")
        return list(reader)


def _write(path: Path, columns: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)


def _species_of(
    taxon: int,
    lineages: dict[int, list[tuple[int, str, str]]],
    listed: dict[int, str],
    placed: dict[int, int],
) -> int | None:
    """The deepest taxon at or above the taxon in `placed.tsv` (its species) or in `species.tsv`."""
    if taxon in placed:  # one missing from the NCBI taxonomy has no lineage
        return placed[taxon]
    for i, _, _ in lineages[taxon]:
        if i in placed:
            return placed[i]
        if i in listed:
            return i
    return None


def proteins_of(
    cur: Any, directory: Path, names: set[tuple[int, str]]
) -> tuple[dict[tuple[int, str], tuple[int, str, str]], list[str]]:
    """The generic viral protein of each (taxon, generic name) of viral interactors, by the files
    of the directory: its species, the species' name and the protein's label; and what the files
    miss, one line each: a taxon under no species, a species not in `species.tsv`, a name with no
    protein."""
    listed = {int(r["ncbi_taxon_id"]): r["name"] for r in _read(directory / "species.tsv", SPECIES)}
    placed = {
        int(r["ncbi_taxon_id"]): int(r["species_ncbi_taxon_id"])
        for r in _read(directory / "placed.tsv", PLACED)
    }
    decided = {
        (int(r["ncbi_taxon_id"]), r["generic_name"]): r["protein"]
        for r in _read(directory / "proteins.tsv", PROTEINS)
    }
    lineages = read.lineages(cur, {t for t, _ in names})
    proteins: dict[tuple[int, str], tuple[int, str, str]] = {}
    unplaced: set[int] = set()
    unlisted: set[int] = set()
    undecided: set[tuple[int, str]] = set()
    for taxon, name in names:
        s = _species_of(taxon, lineages, listed, placed)
        if s is None:
            unplaced.add(taxon)
        elif s not in listed:
            unlisted.add(s)
        elif not decided.get((s, name)):
            undecided.add((s, name))
        else:
            proteins[(taxon, name)] = (s, listed[s], decided[(s, name)])
    missing = [f"taxon under no species\t{t}" for t in sorted(unplaced)]
    missing += [f"species not in species.tsv\t{s}" for s in sorted(unlisted)]
    missing += [f"no protein\t{s} {listed[s]}\t{n}" for s, n in sorted(undecided)]
    return proteins, missing


def sync(cur: Any, directory: Path) -> str:
    """Refresh `species.tsv` and `proteins.tsv` of the directory from Drakkar; the report: the
    counts, then what a person decides."""
    species_rows = _read(directory / "species.tsv", SPECIES)
    placed_rows = _read(directory / "placed.tsv", PLACED)
    placed = {int(r["ncbi_taxon_id"]): int(r["species_ncbi_taxon_id"]) for r in placed_rows}
    protein_rows = _read(directory / "proteins.tsv", PROTEINS)
    listed = {int(r["ncbi_taxon_id"]): r["name"] for r in species_rows}

    # the generic names of the vh descriptions dataset
    cur.execute(
        """
        SELECT v.ncbi_taxon_id, d.name2, count(*) AS descriptions
        FROM descriptions AS d
        JOIN proteins AS v ON v.id = d.protein2_id
        JOIN proteins AS h ON h.id = d.protein1_id
        JOIN proteins_versions AS current
          ON current.accession = h.accession AND current.version = h.version
        WHERE d.deleted_at IS NULL AND v.type = 'v' AND current.reviewed
        GROUP BY v.ncbi_taxon_id, d.name2
        """
    )
    names: list[tuple[int, str, int]] = cur.fetchall()
    # the publications of the live vh descriptions, whatever the snapshot of their interactors
    cur.execute(
        """
        SELECT v.ncbi_taxon_id, a.pmid
        FROM descriptions AS d
        JOIN associations AS a ON a.id = d.association_id
        JOIN proteins AS v ON v.id = d.protein2_id
        WHERE d.deleted_at IS NULL AND v.type = 'v'
        GROUP BY v.ncbi_taxon_id, a.pmid
        """
    )
    pmids: list[tuple[int, int]] = cur.fetchall()
    taxa = {t for t, _, _ in names} | {t for t, _ in pmids}
    lineages = read.lineages(cur, taxa | listed.keys())

    def species_of(taxon: int) -> int | None:
        return _species_of(taxon, lineages, listed, placed)

    publications: dict[int, set[int]] = defaultdict(set)
    for taxon, pmid in pmids:
        s = species_of(taxon)
        if s is not None:
            publications[s].add(pmid)
    families = {
        s: next((i for i, rank, _ in lineages[s] if rank == "family"), None) for s in listed
    }
    # by family, then species, a species in no family last: easy to consult
    species_rows.sort(
        key=lambda r: (
            families[int(r["ncbi_taxon_id"])] is None,
            families[int(r["ncbi_taxon_id"])] or 0,
            int(r["ncbi_taxon_id"]),
        )
    )
    _write(
        directory / "species.tsv",
        SPECIES,
        [
            [families[s] or "", s, r["name"], len(publications[s])]
            for r in species_rows
            for s in [int(r["ncbi_taxon_id"])]
        ],
    )

    if placed_rows:
        placed_rows.sort(key=lambda r: (int(r["species_ncbi_taxon_id"]), int(r["ncbi_taxon_id"])))
        _write(directory / "placed.tsv", PLACED, [[r[c] for c in PLACED] for r in placed_rows])

    exported: dict[tuple[int, str], int] = defaultdict(int)
    unplaced: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for taxon, name, descriptions in names:
        s = species_of(taxon)
        if s is None:
            unplaced[taxon][name] += descriptions
        else:
            exported[(s, name)] += descriptions
    decided = {(int(r["ncbi_taxon_id"]), r["generic_name"]): r["protein"] for r in protein_rows}
    notes = {(int(r["ncbi_taxon_id"]), r["generic_name"]): r["note"] for r in protein_rows}
    removed = sorted(decided.keys() - exported.keys())
    added = sorted(exported.keys() - decided.keys())
    proteins = {key: decided.get(key, "") for key in exported}
    order = {int(r["ncbi_taxon_id"]): i for i, r in enumerate(species_rows)}
    keys = sorted(proteins, key=lambda k: (order.get(k[0], len(order)), k[1].casefold(), k[1]))
    _write(
        directory / "proteins.tsv",
        PROTEINS,
        [[s, n, proteins[(s, n)], notes.get((s, n), "")] for s, n in keys],
    )

    def species(s: int) -> str:
        return f"{s} {listed.get(s, '(not in species.tsv)')}"

    lines = [
        f"species.tsv: {len(species_rows)} species, "
        f"{sum(1 for f in families.values() if f is None)} without a family",
        f"proteins.tsv: {len(proteins)} names, "
        f"{len({(s, p) for (s, _), p in proteins.items() if p})} proteins; "
        f"{len(added)} added, {len(removed)} removed",
    ]
    for s, n in removed:
        lines.append(f"removed\t{species(s)}\t{n}\t{decided[(s, n)] or '-'}")

    lines.append("")
    lines.append("To decide:")
    missing = sorted(s for s, lineage in lineages.items() if s in listed and not lineage)
    for s in missing:
        lines.append(f"species not in the NCBI taxonomy\t{species(s)}")
    found = sorted(t for t, s in placed.items() if s in {i for i, _, _ in lineages.get(t, [])})
    for t in found:
        lines.append(f"placed, now under its species in the NCBI taxonomy (its line can go)\t{t}")
    for t in sorted(unplaced):
        lineage = (
            " < ".join(f"{i} {n}" for i, _, n in lineages[t]) or f"{t} (not in the NCBI taxonomy)"
        )
        shown = ", ".join(f"{n} ({c})" for n, c in sorted(unplaced[t].items(), key=lambda x: -x[1]))
        lines.append(f"taxon under no species\t{lineage}\t{shown}")
    for s, n in keys:
        if not proteins[(s, n)]:
            lines.append(f"no protein\t{species(s)}\t{n}\t{exported[(s, n)]} descriptions")
    for s, n in keys:
        p = proteins[(s, n)]
        if p and p != n and (s, p) in proteins and proteins[(s, p)] != p:
            lines.append(
                f"protein named elsewhere\t{species(s)}\t{n} → {p}, but {p} → {proteins[(s, p)]}"
            )
    if lines[-1] == "To decide:":
        lines.append("nothing")
    return "\n".join(lines)
