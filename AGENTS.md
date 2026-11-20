# Agent instructions

Drakkar is the curation database of virus–human protein–protein interactions. Claude curates it: each description exactly what its publication shows, every write checked, every decision traceable in its note.

## Where things are

- The repository is a uv workspace of two packages, each standing alone with its code, tests, docs and processes; the root only runs their tools together. The Drakkar database is made for many clients and is unaware of the curation: nothing in `database/` names a concept of `curation/` (its agent, skills, batches, full texts, rules, commands). The curation is made for the Drakkar database and uses its concepts freely. It never imports `database`: it reaches the Drakkar database only through the scripts of `database/scripts/` its agents and skills run.
- The READMEs are the map: `README.md` presents the repository, `database/README.md` and `curation/README.md` each package, part by part.
- `database/docs/` is the source of truth on the database, read before acting: `glossary.md` (one meaning per term, used everywhere), `database.md` (structure, states, the publication and description notes, versioning, invariants, writes), `datasets.md` (what the derived datasets mean for curation, the generic viral proteins). `curation/docs/`: `curation-rules.md` (the biological rules of curation: what a right description is, and the evidence for it), `glossary.md` (the curation's own terms).
- A tool is one script of `database/scripts/` or `curation/scripts/`, described in its docstring with the files it reads and writes, read before running it.
- `database/docs/history/` and `curation/docs/history/`: the record of the move from manual curation to Claude's curation, with its dates, counts and measurements, one file each, in the package of its subject. Closed: nothing is added to it. The reference docs never point to it.
- `articles/`: articles about the repository for readers outside it, published on GitHub Pages; `articles/AGENTS.md` holds their rules, read before writing one. The reference docs never point to them.
- `<datadir>/`, the data directory the user's global configuration sets, holds the work directories: `<datadir>/curation/`, the curation's runs, one directory `run<name>/` per run; `<datadir>/exports/`, the exports of the Drakkar database, one directory `run<name>/` per cut run; `<datadir>/uniprot/`, the UniProt releases loaded into the Drakkar database, one directory per release named after it (`2026_04/`): its UniProt files, `taxonomy/` (the NCBI taxonomy loaded with it) and `reports/`. Any other job works in the directory the user names, otherwise ask. Work directories and scratch files are disposable: docs never point to their contents, what a reader needs is written in the doc itself.

## Working with the user

- The skills and docs are instructions for an agent that curates publications and manages Drakkar, with the user supervising its results: not a pipeline where every detail is settled end to end. What matters is the instructions, the process, and data that is easy to use and manage. Not every detail or edge case needs a rule, and no error is dramatic: every version is kept, and a publication can always be curated again.
- Use the user's definitions exactly as given (the glossaries, `database/docs/glossary.md` and `curation/docs/glossary.md`): never merge, regroup, relabel or extend a problem, term or rule; when one seems incomplete, ask one precise question.
- When the user states a principle, apply it to every case it covers in one pass; ask only about cases it does not decide.
- When the user says to wait, start nothing. Run exactly the rule the user stated: no extra check, no arbitrary threshold. Keep a check at the level the user named (checking names is not re-checking interactors) and estimate its cost first; anything more than a quick pass needs approval.
- Low-stakes requests (test data, demos): the simplest thing in minutes, one plain query, no enrichment; extras only afterwards.
- Rewriting a skill, a tool or a process starts from its goal: every step of the old version is questioned before it is kept, and the design is agreed before anything is written or run. A tool is built when its job comes, not before.
- Be precise and short: say what is counted (descriptions, interactors, proteins, sides) and never mix units; one decision at a time; show the special cases, not the obvious ones; plain words, no invariant codes.
- Every count comes from a fresh query or the latest report, never from memory or arithmetic on earlier numbers; tables add up to their total. A result is reported only once the analysis behind it is complete: each count is given once, final, never revised in a later message.
- People name a run by its name: "run 85" is the run named 85, never the run whose ID is 85, unless the message says it is an ID. Every reply names runs by their names; the ID is only for the queries and commands that take one, never a correction to the user.

## Database queries

- The database is big (millions of protein snapshots, the whole NCBI taxonomy): every query must be fast. Check the indexes (`pg_indexes`) and, when unsure, the plan (`EXPLAIN`); set a `statement_timeout` so a bad plan fails fast; aggregate first, then join the small result; time each step.
- SQL is written for a human reader: plain joins, named columns in `GROUP BY` and `ORDER BY`, clear aliases; a complex form only when speed needs it, with a comment saying so.
- Timestamps are `timestamp(0)`: compare with `now()::timestamp(0)`.

## Database writes

- Every job that writes (curation batches, versioning passes, a fix) writes nothing to the database before the user's go on its report. The user supervises every commit: the report shows what the commit would write, the user judges it, and the commit writes what the user approved. So no skill or tool holds back part of a job on its own: the report shows it, the user decides. A dry run writes nothing and needs no go.
- The report leaves no open question to the user. After the go, the orchestrator commits in its own context, without asking again.
- Writes go through the write scripts of `database/scripts/`; plain SQL only when the user allows it for that write.
- Subagents decide and write files, never to the database. A skill writes only where its prompt says; placing and aggregating its output is the orchestrator's job.
- Recomputed values (alignments, identities, coordinates) are written only if our code first reproduces the stored values on the cases that are right; any discrepancy: stop, show it, write nothing.

## Docs and prompts

- Every concept is written once, as one of four things, and everything else points to it: an agent instruction, in this file or, for a process, in its skill or agent file; a doc, for people and agents, in a README, `database/docs/` or `curation/docs/`; an explanation of code, in its docstrings (a tool in its script's, which its `--help` prints, with the files it reads and writes; a format several tools share in the module that reads and writes it; a module and a function in their own); the history of a change, in git and nowhere else. Only the skill and agent prompts repeat, condensed, what they need.
- The instructions and the docs change only with the user's agreement: propose the change, write it after the yes.
- Keep the docs and the prompts up to date with every decision: a change of a format or a tool updates its docstring and the prompts that repeat it.
- The reference docs, `database/docs/` and `curation/docs/`, are explanations and rules for people and for the working agent, timeless and right at reading time: they describe the current rules and the current state. Every paragraph is something the agent needs to act correctly now. No account of how things came to be (what changed, was added or removed, and when), no detail a tool or a database constraint already enforces, no dates, no counts, no results of a run, no status tags, no plans. Every rule written is decided.
- The docs of each package hold its rules; a curation doc points to a database doc, never the reverse. Each doc keeps to its scope: `curation-rules.md` the biology, `database.md` the data, its notes and its invariants; no process in a doc.
- The skills and the agent files hold the processes, each self-contained: the whole process it runs, the formats it writes and the tools it uses, condensed, so that an agent spends its context on its job, not on reading docs. It reads no doc; it repeats of a doc or a docstring only the short parts it needs (the columns of a file, the note lines it writes). Two prompts may give the same instruction.
- The READMEs, the repository's and each package's, present them to people: a projection of their content at a level that only a big refactoring of their functionality changes (what each part is for, how the parts fit, how to run it), pointing to the details, never listing what changes with the code (its commands, options, formats, rules).
- Everything is referenced by a stable ID, never by its number or its wording: a section by the ID its heading ends with, `<a id="<id>"></a>`, given when it is first referenced and never changed (`database.md#notes`, `#notes` in its own file); an invariant by its ID (`D5`). Headings are not numbered; a numbered list gives an order, and nothing points to an item by its number.
- Markdown is formatted with `uv run mdformat --wrap no --number --compact-tables database/docs/ database/skills/ database/generic/ curation/docs/ curation/agents/ curation/skills/ articles/ AGENTS.md README.md database/README.md curation/README.md`.

## Python

- uv for environments and dependencies, ruff for linting and formatting, pyright for type checking, pytest for tests (`uv run pytest`: a test database, never Drakkar).
- A tool is a function of a module, taking its parameters and checking that they are valid together; its script, `<package>/scripts/<tool>.py`, the tool's only entry point, run by its path from the repository root (`uv run ./database/scripts/read.py`), parses the arguments into those parameters, calls it, prints its result and sets the exit code. A module never parses arguments, prints a result or exits. A tool on the database gets it from its script: a read, a cursor on a read-only connection; a write, a connection with no transaction in progress, its whole work in one transaction it ends itself, committed only when asked and nothing failed, rolled back otherwise.
- Parameters go from the most general to the most specific, in a script as in a function: `diff.py <pmid> <file>`, `mapping.py <accession> <sequence>...`.

## Git

- Never commit, amend or push without the user's explicit request for it: write the files, show them, and ask.
- A commit message is a short title in the imperative, then, after a blank line, a body whose lines are never wrapped by hand: one line per paragraph, saying what changes and why.
