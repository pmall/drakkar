# database

The Drakkar database and everything around it: its structure, the tools that read, check and write it, the UniProt releases it loads and the datasets it exports. It is made for many clients and knows nothing of the curation that uses it.

- [`docs/`](docs/): [`glossary.md`](docs/glossary.md), the terms; [`database.md`](docs/database.md), the tables, the states of a publication, the notes, versioning and the invariants; [`datasets.md`](docs/datasets.md), what the derived datasets mean.
- [`src/database/`](src/database/): the functions that read Drakkar, write it (a dry run unless told to commit), check its invariants, load the UniProt releases and export the derived datasets.
- [`scripts/`](scripts/): one script per tool, run by its path from the repository root, `uv run ./database/scripts/<tool>.py`; each is described in its docstring, which `--help` prints.
- [`sql/schema.sql`](sql/schema.sql): the structure of the database.
- [`tests/`](tests/): the tests, on a test database built from the structure, never Drakkar.
- [`skills/export/`](skills/export/SKILL.md): the export of the derived datasets, the generic viral proteins brought in step first.
- [`generic/`](generic/): the species and generic viral proteins of the vh descriptions dataset.
