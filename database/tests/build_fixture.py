"""Write the test fixture, `tests/fixture.sql`, from the Drakkar database: the tests load it after
`sql/schema.sql` (`database/scripts/schema.py`).

The fixture is a few real publications, with every version of their descriptions, the snapshots
they use and the current snapshots of the same proteins, the taxa of those proteins with their
lineage, and all the methods. Its rows follow the columns of the schema: run it again after
`schema.py` when the structure changes, or to change the fixture:

    uv run python tests/build_fixture.py
"""

from pathlib import Path

import psycopg

from database.db import connect

HERE = Path(__file__).parent

# (run ID, PMID): why it is in the fixture.
PUBLICATIONS = {
    (1, 22046132): "Q6VA95 N: an interactor carried by 2 descriptions (rename)",
    (44, 31690057): "P26662 810-1026 NS2-3: a mature protein",
    (69, 38566321): "P25223 P",
    (1, 8626429): "a mapping below 100 % with isoforms",
    (1, 9858596): "mappings below 100 % with isoforms",
    (1, 10777214): "a human interactor on an obsolete snapshot",
    (12, 25031347): "selected, no pass yet",
    (56, 34799561): "curated with a curator note",
    (30, 24379396): "curated, empty note",
    (31, 15471871): "hh, several versions",
    (33, 7499434): "hh, several versions",
}

TABLES = {
    "runs": "SELECT * FROM runs WHERE id = ANY(%(runs)s)",
    "publications": "SELECT * FROM publications WHERE pmid = ANY(%(pmids)s)",
    "associations": "SELECT * FROM associations WHERE id = ANY(%(associations)s)",
    "methods": "SELECT * FROM methods",
    "taxon": "SELECT * FROM taxon WHERE taxon_id = ANY(%(taxa)s)",
    "taxon_name": "SELECT * FROM taxon_name WHERE taxon_id = ANY(%(taxa)s)",
    "proteins": "SELECT * FROM proteins WHERE id = ANY(%(proteins)s)",
    "proteins_versions": "SELECT * FROM proteins_versions WHERE accession = ANY(%(accessions)s)",
    "descriptions_vh": "SELECT * FROM descriptions_vh WHERE association_id = ANY(%(associations)s)",
    "descriptions_hh": "SELECT * FROM descriptions_hh WHERE association_id = ANY(%(associations)s)",
}
SEQUENCES = {
    "associations_id_seq": "associations",
    "methods_id_seq": "methods",
    "proteins_id_seq": "proteins",
    "runs_id_seq": "runs",
}


def fixture() -> str:
    with connect(readonly=True) as conn, psycopg.ClientCursor(conn) as cur:
        pairs = list(PUBLICATIONS)
        cur.execute(
            """
            SELECT a.id FROM associations AS a
            JOIN unnest(%s::int[], %s::bigint[]) AS wanted (run_id, pmid) USING (run_id, pmid)
            """,
            ([r for r, _ in pairs], [p for _, p in pairs]),
        )
        ids = [r[0] for r in cur.fetchall()]
        assert len(ids) == len(pairs), ids
        cur.execute(
            """
            SELECT protein1_id FROM descriptions_vh WHERE association_id = ANY(%(ids)s)
            UNION SELECT protein2_id FROM descriptions_vh WHERE association_id = ANY(%(ids)s)
            UNION SELECT protein1_id FROM descriptions_hh WHERE association_id = ANY(%(ids)s)
            UNION SELECT protein2_id FROM descriptions_hh WHERE association_id = ANY(%(ids)s)
            """,
            {"ids": ids},
        )
        used = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT accession FROM proteins WHERE id = ANY(%s)", (used,))
        accessions = [r[0] for r in cur.fetchall()]
        # The snapshots used, and the current snapshot of each protein.
        cur.execute(
            """
            SELECT p.id FROM proteins AS p
            JOIN proteins_versions AS v ON v.accession = p.accession AND v.version = p.version
            WHERE p.accession = ANY(%s)
            """,
            (accessions,),
        )
        proteins = sorted(set(used) | {r[0] for r in cur.fetchall()})
        cur.execute(
            """
            WITH RECURSIVE walk AS (
                SELECT t.taxon_id, t.parent_taxon_id FROM taxon AS t
                WHERE t.ncbi_taxon_id IN (SELECT ncbi_taxon_id FROM proteins WHERE id = ANY(%s))
                UNION
                SELECT t.taxon_id, t.parent_taxon_id FROM walk AS w
                JOIN taxon AS t ON t.taxon_id = w.parent_taxon_id
            )
            SELECT taxon_id FROM walk
            """,
            (proteins,),
        )
        taxa = [r[0] for r in cur.fetchall()]
        params = {
            "runs": sorted({r for r, _ in pairs}),
            "pmids": sorted({p for _, p in pairs}),
            "associations": ids,
            "taxa": taxa,
            "proteins": proteins,
            "accessions": accessions,
        }
        out = ["SET client_encoding = 'UTF8';", ""]
        for table, query in TABLES.items():
            out.append(f"COPY public.{table} FROM stdin;")
            sql = cur.mogrify(query, params)
            with cur.copy(f"COPY ({sql} ORDER BY 1, 2) TO STDOUT") as copy:
                out.append(b"".join(bytes(block) for block in copy).decode().rstrip("\n"))
            out += ["\\.", ""]
        for sequence, table in SEQUENCES.items():
            out.append(f"SELECT setval('public.{sequence}', (SELECT max(id) FROM public.{table}));")
        out.append(
            "SELECT setval('public.taxon_pk_seq', (SELECT max(taxon_id) FROM public.taxon));"
        )
    return "\n".join(out) + "\n"


def main() -> None:
    (HERE / "fixture.sql").write_text(fixture())


if __name__ == "__main__":
    main()
