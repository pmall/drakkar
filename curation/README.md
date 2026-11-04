# curation

The curation of Drakkar by an AI agent. A client of the Drakkar database, it never imports its code: it reaches it only through the `database-*` commands its agent and skill run.

- [`agents/curator.md`](agents/curator.md): the curator agent, which curates one publication from its full text into its descriptions and its publication note. Its prompt is the whole curation.
- [`skills/fetch/`](skills/fetch/SKILL.md): the download of a run's full texts into its pool, and the forming of its next batch from the publications whose download is complete.
- [`skills/curate/`](skills/curate/SKILL.md): the curation of a batch, each publication by a curator agent, merged into files that pass the dry run and reported; the commit comes when the user asks.
- [`docs/`](docs/): [`curation-rules.md`](docs/curation-rules.md), the biological rules of the curator's prompt, explained; [`glossary.md`](docs/glossary.md), the curation's own terms.
- [`src/curation/`](src/curation/): the `curation-*` commands, which fetch and convert full texts, read NCBI sequences and build a batch's publications file, and never touch the database; each is described in its module's docstring, which `uv run <command> --help` prints.
- [`tests/`](tests/): the tests, with their samples, no database.
