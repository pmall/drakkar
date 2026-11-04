# Drakkar

Drakkar is the curation database of virus–human protein–protein interactions; Vinland, the published database, is rebuilt from it at each of its releases. This repository is where an AI agent curates Drakkar under the user's supervision: the Drakkar database and everything around it, the curation that uses it, and the instructions the agent follows.

## What Drakkar holds

A **description** is one piece of evidence of an interaction: a publication, a detection method, a human interactor and a viral interactor, recorded once for that combination. Its **mappings** are the subsequences of either side that the experiment shows are enough for the interaction. The interactors are UniProt entries; a viral interactor can be a mature protein, a part of a cleaved polyprotein given by its coordinates, and is named by its generic name (`NS1`, `Vpr`), whatever UniProt or the publication calls it.

Descriptions are versioned: a revision makes a new version under the same stable ID, a removal ends it, and nothing is ever deleted. Each UniProt release is kept as snapshots of its entries, and a description points to the snapshots it was curated on, so it stays exact on them when UniProt changes. Every write is checked against a set of invariants on the whole database. Human–human descriptions, from earlier curation, are kept and maintained alongside, without new curation.

## The life of a publication

1. **A run**: a PubMed query gives a run of publications, each `pending`.
2. **Pre-curation**: from its title and abstract, each is `selected` or `discarded`.
3. **Curation**: the agent curates each selected publication from its full text and supplementary files, into its descriptions and its publication note, and the publication is `curated`. When a relevant file is missing, it stays `selected`, for a manual pass.
4. **UniProt releases**: each release loads the new snapshots, and the versioning pass moves the obsolete interactors of the live descriptions to current snapshots.
5. **Exports**: the derived datasets, files for other applications, from the live descriptions. The vh descriptions show each interaction as one human Swiss-Prot entry × one generic viral protein, one node of an interaction graph.

## The idea

The agent curates; the user supervises. The agent reads each publication, decides its descriptions and writes them into files. Drakkar's writes check those files against the whole database, and nothing reaches Drakkar before the user's go on a report. Every version of every description is kept, so no write is irreversible and a publication can always be curated again. Each publication note and each description note says why, so every decision can be traced without the conversation that made it.

## Two packages

The repository is a uv workspace of two packages, each standing alone with its code, tests, docs and processes:

- [`database/`](database/README.md), **the Drakkar database**: its structure, the commands that read, check and write it, the only way to write to it, the UniProt releases it loads and the datasets it exports. It is made for many clients and knows nothing of the curation.
- [`curation/`](curation/README.md), **the curation**, a client of the Drakkar database: the `curate` skill, which curates one publication, the `fetch` skill, which downloads the full texts of a batch of them, the `curate-batch` skill, which curates a batch, one curator agent per publication, the `review` and `review-batch` skills, which review a curated publication or batch, and the commands that fetch and convert full texts. It reaches the database only through its commands.

[`AGENTS.md`](AGENTS.md) holds the agent's instructions: how it works with the user, writes to and queries the database, and where everything is. [`.claude/`](.claude/) links the agent and the skills of both packages for Claude Code.

## Running it

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), PostgreSQL with Drakkar, and Claude Code.

```sh
uv sync                 # both packages
cp .env.example .env    # then fill it in, as its comments say
```

In Claude Code, run from the repository:

- `/fetch` downloads the full texts of a run's publications and forms its next batch from those whose download is complete.
- `/curate-batch` curates a batch, one curator agent per publication, and ends with its dry run and report; nothing is written before the user asks for the commit.
- `/review-batch`, optional, reviews a curated batch, one reviewer agent per publication, and reports what is wrong; it writes nothing.
- `/curate` curates one publication from its directory into its descriptions and its note, as files.
- `/review` reviews one curated publication and replies what is wrong; it writes nothing.
- `/export` exports the derived datasets.

Each skill is started by the user only; the curator and reviewer agents preload `curate` and `review`. The commands run from the repository root, `uv run <command>`; `--help` describes each.

## Development

```sh
uv run pytest           # on a test database, never Drakkar
uv run ruff check && uv run ruff format
uv run pyright
```

The conventions, for the agent and for people: [`AGENTS.md`](AGENTS.md).
