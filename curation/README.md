# curation

The curation of Drakkar by an AI agent. A client of the Drakkar database, it never imports its code: it reaches it only through the scripts of `database/scripts/` its agents and skills run.

- [`skills/precurate-one/`](skills/precurate-one/SKILL.md): the pre-curation of one batch of publications, each selected or discarded from its title and abstract.
- [`agents/precurator.md`](agents/precurator.md): the precurator agent, which runs the `precurate-one` skill on one batch; its file holds only its settings.
- [`skills/precurate/`](skills/precurate/SKILL.md): the pre-curation of a run's pending publications, each batch by a precurator agent, merged into a file that passes the dry run and reported; the commit comes when the user asks.
- [`skills/curate-one/`](skills/curate-one/SKILL.md): the curation of one publication from its full text into its descriptions and its publication note. Its prompt is the whole curation.
- [`agents/curator.md`](agents/curator.md): the curator agent, which runs the `curate-one` skill on one publication of a batch; its file holds only its settings.
- [`skills/fetch/`](skills/fetch/SKILL.md): the download of a run's full texts into its pool, and the forming of its next batch from the publications whose download is complete.
- [`skills/curate/`](skills/curate/SKILL.md): the curation of a batch, each publication by a curator agent, then reviewed by a reviewer agent and fixed by its curator, merged into files that pass the dry run and reported; the commit comes when the user asks.
- [`skills/review-one/`](skills/review-one/SKILL.md): the review of one curated publication, a hunt for what is wrong in its descriptions and its note, against its full text.
- [`agents/reviewer.md`](agents/reviewer.md): the reviewer agent, which runs the `review-one` skill on one publication of a batch; its file holds only its settings.
- [`skills/review/`](skills/review/SKILL.md): the optional review of a curated batch, each publication by a reviewer agent, what they find checked and reported, then the fixes the user directs.
- [`docs/`](docs/): [`curation-rules.md`](docs/curation-rules.md), the biological rules of curation, which the `curate-one` skill's prompt repeats, condensed; [`glossary.md`](docs/glossary.md), the curation's own terms.
- [`src/curation/`](src/curation/): the functions that fetch and convert full texts, read NCBI sequences and build a batch's publications file, and never touch the database.
- [`scripts/`](scripts/): one script per tool, run by its path from the repository root, `uv run ./curation/scripts/<tool>.py`; each is described in its docstring, which `--help` prints.
- [`tests/`](tests/): the tests, with their samples, no database.
