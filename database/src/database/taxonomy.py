"""Load or update the NCBI taxonomy (`taxon`, `taxon_name`) for a UniProt release.

    uv run database-taxonomy <workdir>/<release> [--commit]

The first command of a release, before `database-uniprot` (`uniprot.py`), on the same directory,
named after the release. The taxonomy is scoped by UniProt release: the dump loaded with a
release is kept next to it, in `<workdir>/<release>/taxonomy/`, the NCBI `taxdump.tar.gz`
unpacked (`nodes.dmp`, `names.dmp`, `merged.dmp`).

Python port of BioSQL's `load_ncbi_taxonomy.pl --nodelete`, as the legacy drakkar-taxonomy ran it:

- nodes are matched on their NCBI taxon ID: new ones are inserted, changed ones updated;
- retired nodes (absent from the dump) are kept, because proteins may still reference them; the
  log counts those used by proteins, and those merged into another node (`merged.dmp`);
- the nested set (left_value, right_value) is rebuilt from the root, children ordered by NCBI ID;
- the names of the nodes present in the dump are replaced. Unlike the Perl script, the names
  of retired nodes are kept, so old proteins keep a scientific name;
- `taxon.search`, all the names of a taxon in one text for `database-read taxon`, is recomputed
  for the taxa whose names changed.

Everything runs in one transaction. Without --commit, a dry run: it is rolled back.
"""

import argparse
import sys
import time
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import LiteralString

from database.db import connect

NAME_MAX_LENGTH = 255
ROOT_NCBI_TAXON_ID = 1
# `taxon.search`: the names of a taxon, its scientific name first, for `database-read taxon`
# (trigram-indexed). Recomputed for the taxa of `tmp_changed`.
SEARCH: LiteralString = """
    UPDATE taxon AS t SET search = names.search
    FROM (
        SELECT c.taxon_id,
               string_agg(n.name, ' | ' ORDER BY n.name_class <> 'scientific name', n.name)
                   AS search
        FROM tmp_changed AS c LEFT JOIN taxon_name AS n ON n.taxon_id = c.taxon_id
        GROUP BY c.taxon_id
    ) AS names
    WHERE t.taxon_id = names.taxon_id AND t.search IS DISTINCT FROM names.search
"""


def read_dmp(path: Path) -> Iterator[list[str]]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            yield line.rstrip("\n").removesuffix("\t|").split("\t|\t")


def log(start: float, message: str) -> None:
    print(f"[{time.time() - start:7.1f}s] {message}", file=sys.stderr, flush=True)


def nested_set(rows: list[tuple[int, int | None, int]], root: int) -> dict[int, tuple[int, int]]:
    """Return {taxon_id: (left, right)} for the nodes reachable from root.

    rows are (taxon_id, parent_taxon_id, ncbi_taxon_id). Children are visited in NCBI ID order.
    """
    children: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for taxon_id, parent_id, ncbi_id in rows:
        if parent_id is not None and parent_id != taxon_id:
            children[parent_id].append((ncbi_id, taxon_id))
    for siblings in children.values():
        siblings.sort()

    values: dict[int, tuple[int, int]] = {}
    left: dict[int, int] = {}
    counter = 1
    left[root] = counter
    stack = [(root, iter(children.get(root, [])))]
    while stack:
        node, siblings = stack[-1]
        child = next(siblings, None)
        counter += 1
        if child is None:
            values[node] = (left.pop(node), counter)
            stack.pop()
        else:
            left[child[1]] = counter
            stack.append((child[1], iter(children.get(child[1], []))))
    return values


def load(release_directory: Path, *, commit: bool) -> None:
    start = time.time()
    directory = release_directory / "taxonomy"
    with connect() as conn:
        cur = conn.cursor()

        log(start, "reading nodes.dmp")
        cur.execute("""
            CREATE TEMP TABLE tmp_nodes (
                ncbi_taxon_id integer PRIMARY KEY,
                parent_ncbi_taxon_id integer NOT NULL,
                node_rank varchar(32),
                genetic_code smallint,
                mito_genetic_code smallint
            ) ON COMMIT DROP
        """)
        with cur.copy("COPY tmp_nodes FROM STDIN") as copy:
            for row in read_dmp(directory / "nodes.dmp"):
                copy.write_row((row[0], row[1], row[2], row[6], row[8]))

        cur.execute("""
            INSERT INTO taxon (ncbi_taxon_id, node_rank, genetic_code, mito_genetic_code)
            SELECT n.ncbi_taxon_id, n.node_rank, n.genetic_code, n.mito_genetic_code
            FROM tmp_nodes AS n
            WHERE NOT EXISTS (SELECT 1 FROM taxon AS t WHERE t.ncbi_taxon_id = n.ncbi_taxon_id)
        """)
        inserted = cur.rowcount
        cur.execute("""
            UPDATE taxon AS t
            SET parent_taxon_id = parent.taxon_id, node_rank = n.node_rank,
                genetic_code = n.genetic_code, mito_genetic_code = n.mito_genetic_code
            FROM tmp_nodes AS n
            JOIN taxon AS parent ON parent.ncbi_taxon_id = n.parent_ncbi_taxon_id
            WHERE t.ncbi_taxon_id = n.ncbi_taxon_id
            AND (t.parent_taxon_id, t.node_rank, t.genetic_code, t.mito_genetic_code)
                IS DISTINCT FROM (parent.taxon_id, n.node_rank, n.genetic_code, n.mito_genetic_code)
        """)
        updated = cur.rowcount - inserted  # new nodes get their parent here too
        log(start, f"nodes: {inserted} inserted, {updated} updated")

        log(start, "rebuilding the nested set")
        cur.execute(
            "SELECT taxon_id, parent_taxon_id, ncbi_taxon_id, left_value, right_value FROM taxon"
        )
        rows = cur.fetchall()
        root = next(r[0] for r in rows if r[2] == ROOT_NCBI_TAXON_ID)
        values = nested_set([(r[0], r[1], r[2]) for r in rows], root)
        changes = [
            (r[0], *values.get(r[0], (None, None)))
            for r in rows
            if values.get(r[0], (None, None)) != (r[3], r[4])
        ]
        unreachable = len(rows) - len(values)
        cur.execute("""
            CREATE TEMP TABLE tmp_nested_set (
                taxon_id integer PRIMARY KEY, left_value integer, right_value integer
            ) ON COMMIT DROP
        """)
        with cur.copy("COPY tmp_nested_set FROM STDIN") as copy:
            for change in changes:
                copy.write_row(change)
        # left_value and right_value are unique: drop the constraints during the update, so that
        # each row is written once, and recreate them after (this also checks the result).
        cur.execute("""
            ALTER TABLE taxon DROP CONSTRAINT xaktaxon_left_value,
                              DROP CONSTRAINT xaktaxon_right_value
        """)
        cur.execute("""
            UPDATE taxon AS t SET left_value = s.left_value, right_value = s.right_value
            FROM tmp_nested_set AS s WHERE t.taxon_id = s.taxon_id
        """)
        cur.execute("""
            ALTER TABLE taxon ADD CONSTRAINT xaktaxon_left_value UNIQUE (left_value),
                              ADD CONSTRAINT xaktaxon_right_value UNIQUE (right_value)
        """)
        log(start, f"nested set: {len(changes)} nodes changed, {unreachable} unreachable")

        log(start, "reading names.dmp")
        cur.execute("""
            CREATE TEMP TABLE tmp_names (
                ncbi_taxon_id integer NOT NULL,
                name varchar NOT NULL,
                name_class varchar(32) NOT NULL
            ) ON COMMIT DROP
        """)
        too_long: list[list[str]] = []
        with cur.copy("COPY tmp_names FROM STDIN") as copy:
            for row in read_dmp(directory / "names.dmp"):
                if len(row[1]) > NAME_MAX_LENGTH:
                    too_long.append(row)
                else:
                    copy.write_row((row[0], row[1], row[3]))
        # Only the differences are written: most names do not change between two dumps.
        cur.execute("""
            CREATE TEMP TABLE tmp_taxon_names ON COMMIT DROP AS
            SELECT DISTINCT t.taxon_id, n.name, n.name_class
            FROM tmp_names AS n JOIN taxon AS t USING (ncbi_taxon_id)
        """)
        cur.execute("CREATE INDEX ON tmp_taxon_names (taxon_id, name, name_class)")
        cur.execute("ANALYZE tmp_taxon_names")
        cur.execute("CREATE TEMP TABLE tmp_changed (taxon_id integer) ON COMMIT DROP")
        cur.execute("""
            WITH deleted AS (
                DELETE FROM taxon_name AS tn USING taxon AS t, tmp_nodes AS n
                WHERE tn.taxon_id = t.taxon_id AND t.ncbi_taxon_id = n.ncbi_taxon_id
                AND NOT EXISTS (
                    SELECT 1 FROM tmp_taxon_names AS dump
                    WHERE dump.taxon_id = tn.taxon_id AND dump.name = tn.name
                    AND dump.name_class = tn.name_class
                )
                RETURNING tn.taxon_id
            )
            INSERT INTO tmp_changed SELECT taxon_id FROM deleted
        """)
        deleted_names = cur.rowcount
        # The names to insert, once to note their taxa (an INSERT on `taxon_name`, which has a
        # rule, cannot return them), then inserted.
        cur.execute("""
            CREATE TEMP TABLE tmp_new_names ON COMMIT DROP AS
            SELECT dump.taxon_id, dump.name, dump.name_class FROM tmp_taxon_names AS dump
            WHERE NOT EXISTS (
                SELECT 1 FROM taxon_name AS tn
                WHERE tn.taxon_id = dump.taxon_id AND tn.name = dump.name
                AND tn.name_class = dump.name_class
            )
        """)
        cur.execute("INSERT INTO tmp_changed SELECT taxon_id FROM tmp_new_names")
        cur.execute("""
            INSERT INTO taxon_name (taxon_id, name, name_class)
            SELECT taxon_id, name, name_class FROM tmp_new_names
        """)
        log(start, f"names: {deleted_names} deleted, {cur.rowcount} inserted")
        cur.execute(SEARCH)
        log(start, f"search: {cur.rowcount} taxa")
        for row in too_long:
            log(start, f"name skipped (> {NAME_MAX_LENGTH} characters): taxon {row[0]}, {row[3]}")

        merged: dict[int, int] = {
            int(row[0]): int(row[1]) for row in read_dmp(directory / "merged.dmp")
        }
        cur.execute("""
            SELECT t.ncbi_taxon_id, count(p.id)
            FROM taxon AS t LEFT JOIN proteins AS p ON p.ncbi_taxon_id = t.ncbi_taxon_id
            WHERE NOT EXISTS (SELECT 1 FROM tmp_nodes AS n WHERE n.ncbi_taxon_id = t.ncbi_taxon_id)
            GROUP BY t.ncbi_taxon_id
        """)
        retired = cur.fetchall()
        used = [(taxon, n) for taxon, n in retired if n > 0]
        log(
            start,
            f"retired nodes kept: {len(retired)}, {len(used)} used by proteins"
            f" ({sum(1 for taxon, _ in used if taxon in merged)} merged into another node)",
        )

        if commit:
            conn.commit()
            log(start, "committed")
        else:
            conn.rollback()
            log(start, "dry run: rolled back")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("release_directory", type=Path)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    load(args.release_directory, commit=args.commit)
