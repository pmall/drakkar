---
name: curate
disable-model-invocation: true
description: "Curation batch: publications, each curated by a curator agent, merged into batch files written after the user's go. Use when the user asks to curate publications; the prompt may set the run, the batch directory, the publications or their number."
---

# Curation batch

You run a curation batch: publications, each curated by a `curator` agent from its full text; you merge the results, dry-run them, report, and write them after the user's go. Read no publication and no doc: this skill is the whole process.

1. **Parameters**, from the prompt, otherwise by default:

   - `<workdir>`: the curation's root directory.
   - `<run>`: the oldest run with publications `selected` with no AI pass and no live description.
   - `<batch>`: the batch directory, `<workdir>/run<run>/batch<n>/`, `<n>` the next batch number in `<workdir>/run<run>/`.
   - The publications: 20 at most of the run's publications `selected` with no AI pass, with no live description and listed in no `pmids.txt` of the run's batches.
   - The author: your model ID as your system prompt gives it, `$CLAUDE_EFFORT` your effort, `$AI_AGENT` the Claude Code running you and `git rev-parse --short HEAD` the commit of this repository, as in `claude-opus-5-5 (effort high, claude-code_2-1-312_agent, commit 3f06368)`; the curators run on the same model and effort.

   Write them at once, as the model and the effort may change during the session and other sessions select their publications outside this batch: `mkdir -p <batch> && echo "<model> (effort $CLAUDE_EFFORT, $AI_AGENT, commit $(git rev-parse --short HEAD))" > <batch>/author.txt`, then the publications in `<batch>/pmids.txt`, one per line. `pmids.txt` is the batch, never changed.

2. **Full texts**: a publication directory, `<batch>/<pmid>/`, with its `manifest.json` is ready (files the user provided). Fetch the others: `mkdir -p <batch>/<pmid> && uv run curation-fetch <batch>/<pmid> <pmid> > <batch>/<pmid>/fetch.txt`. The report's first line says where the article comes from, or why there is none; the manifest is written only when the article could be had and converted. Read the reports, never the full texts.

   - `Full text: not downloaded` (free, but no copy could be downloaded): fetch once more, as the failure may pass; still not downloaded, try the browser (below).
   - Still without the article (`Full text: closed`, not downloaded, or not converted): no curator; write its note in `<batch>/<pmid>/curation.txt`: `SELECTED`, then why there is no full text.

3. **Curate**: one `curator` agent per publication with a manifest, a few at a time, sent only `dir: <batch>/<pmid>`, `pmid: <pmid>`. It writes `descriptions.jsonl` and `curation.txt` in its directory. Without them, run it once more; still without them, write its note in `<batch>/<pmid>/curation.txt`: `SELECTED`, then that its curation did not finish.

   - A curator's `SELECTED` note names the files it could not have: try them in the browser; with any of them had, resume that curator (SendMessage) to curate again with them. Once per publication.

4. **Merge**: `cat <batch>/*/descriptions.jsonl > <batch>/descriptions.jsonl`, then `uv run curation-notes <batch>`, which writes `<batch>/publications.jsonl` from the publications' `curation.txt`, the state from the note's first word. The write dates the note.

5. **Dry run**: `uv run database-batch <batch>` applies and checks everything in one transaction, then rolls it back. Report its refused rows and errors as they are, without fixing them.

6. **Reply**: what each batch file holds, in descriptions and publications; the refused rows and errors; the publications without the article, not curated or with a relevant file missing, with why; from the notes, the `best-effort` values and the supplementary files downloaded or not; from the agents' replies, the tool errors.

7. **Commit**, after the go: `uv run database-batch <batch> --author "$(cat <batch>/author.txt)" --commit` writes the new descriptions, the publication states and notes, each note after its date and the author recorded at the start (`[2026-10-29, claude-opus-5-5 (effort high, claude-code_2-1-312_agent, commit 3f06368)] CURATED …`).

## Browser

When your session has browser tools, the browser is the last resort for the files the tools could not download: sites block robots, not a browser. The article comes only from the copies the fetch report tried, never one declaring a paywall; a page giving only the abstract gives no access. A human check (a captcha) is passed by the user, never by you: ask them. Move the browser's downloads into `<batch>/<pmid>/`, convert them with `uv run curation-parse <batch>/<pmid> <file>...`, which prints each file's manifest entry, and write or complete `manifest.json` (`article`, `supplements` each with its `name`, `figures`).
