# curation

The curation of Drakkar by an AI agent. A client of the Drakkar database, it never imports its code: it reaches it only through the `database-*` commands its agent and skill run.

- [`agents/curator.md`](agents/curator.md): the curator agent, which curates one publication from its full text into its descriptions and its publication note. Its prompt is the whole curation.
- [`skills/curate/`](skills/curate/SKILL.md): the curation of a batch of publications, each by a curator agent, merged, dry-run, reported and written after the user's go.
- [`docs/`](docs/): [`curation-rules.md`](docs/curation-rules.md), the biological rules of the curator's prompt, explained; [`glossary.md`](docs/glossary.md), the curation's own terms.
- [`src/curation/`](src/curation/): the `curation-*` commands, which fetch and convert full texts, read NCBI sequences and build a batch's publications file, and never touch the database; each is described in its module's docstring, which `uv run <command> --help` prints.
- [`tests/`](tests/): the tests, with their samples, no database.
