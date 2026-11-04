---
name: curate-batch
disable-model-invocation: true
description: "Curation of a batch formed by the fetch skill: its publications, each curated by a curator agent, merged into the batch files that pass the dry run, committed only when the user asks. The prompt may name the batch."
---

# Curate a batch

You curate a batch: its publications, each curated by a `curator` agent from its full text; you merge the results, dry-run them and report. The goal is a batch that passes the dry run. Read no publication and no doc: this skill is the whole process.

1. **Batch**: `<batch>`, the batch directory the prompt names, otherwise the oldest batch, in the oldest run of `<workdir>` (the curation's root directory), with a `pmids.txt` and no `author.txt`. `pmids.txt` is the batch, never changed. Check the directory against it before anything else: one publication directory `<batch>/<pmid>/`, with its `manifest.json`, per PMID, and no other. Anything else: stop and report it.

   Then write the author, which takes the batch, at once, as the model and the effort may change during the session: `echo "<model> (effort $CLAUDE_EFFORT, $AI_AGENT, commit $(git rev-parse --short HEAD))" > <batch>/author.txt`: your model ID as your system prompt gives it, `$CLAUDE_EFFORT` your effort, `$AI_AGENT` the Claude Code running you and `git rev-parse --short HEAD` the commit of this repository, as in `claude-opus-5-5 (effort high, claude-code_2-1-312_agent, commit 3f06368)`; the curators run on the same model and effort.

2. **Curate**: one `curator` agent per publication, a few at a time, sent only `dir: <batch>/<pmid>`, `pmid: <pmid>`. It writes `descriptions.jsonl` and `curation.txt` in its directory. Without them, run it once more; still without them, write its note in `<batch>/<pmid>/curation.txt`: `SELECTED`, then that its curation did not finish.

   - A curator's `SELECTED` note names the files it could not have: try to have them as any file, with the tools (`uv run curation-download <batch>/<pmid>/work <url>...`), then the browser as the last resort (below). With any of them had, resume that curator (SendMessage) to curate again with them, once per publication. A file not had leaves the publication `selected`, with its descriptions.

3. **Merge**: `cat <batch>/*/descriptions.jsonl > <batch>/descriptions.jsonl`, then `uv run curation-notes <batch>`, which writes `<batch>/publications.jsonl` from the publications' `curation.txt`, the state from the note's first word. The write dates the note.

4. **Dry run**: `uv run database-batch <batch>` applies and checks everything in one transaction, then rolls it back. When it refuses rows or finds errors, report them as they are; the user directs the fix (a publication's diff against its live descriptions, `uv run database-diff <pmid> <file>`, included), then dry-run again.

5. **Reply**: whether the batch passes the dry run, else its refused rows and errors; what each batch file holds, in descriptions and publications; the publications with a relevant file missing, with why; from the notes, the `best-effort` values and the supplementary files downloaded or not; from the agents' replies, the tool errors. Never ask for the commit.

**Commit**, only when the user asks for it: `uv run database-batch <batch> --author "$(cat <batch>/author.txt)" --commit` writes the new descriptions, the publication states and notes, each note after its date and the author recorded at the start (`[2026-10-29, claude-opus-5-5 (effort high, claude-code_2-1-312_agent, commit 3f06368)] CURATED …`).

## Browser

When your session has browser tools, the browser is the last resort for the files the tools could not download: sites block robots, not a browser. A human check (a captcha) is passed by the user, never by you: ask them. A closed file comes through the library proxy, once the user has logged it in: `https://doi-org.docelec.univ-lyon1.fr/<doi>` opens the article at its publisher; a login page means the session expired: ask the user to log in again, and never enter credentials.

The browser saves each download in its download folder without asking; ask the user where that folder is when you do not know. It allows one download per page: navigate the tab to each file's URL. A download appears several seconds late, sometimes named `<name> (1).<ext>`. Move each one at once into `<batch>/<pmid>/<pmid>.supp/`, under its own name, an archive unpacked without its videos, and leave the folder's other files alone. Convert them with `uv run curation-parse <batch>/<pmid> <file>...`, which prints the manifest entries of each file and of its images, and complete `manifest.json` (`supplements` each with its `name`).
