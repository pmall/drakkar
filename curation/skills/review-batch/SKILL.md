---
name: review-batch
disable-model-invocation: true
description: "Review of a curated batch: each publication reviewed by a reviewer agent, the wrong things it finds checked and reported to the user, then the fixes the user directs, written to Drakkar when the user asks for the commit. The prompt names the batch."
---

# Review a batch

You review a curated batch: each publication is reviewed by a `reviewer` agent, which looks for what the curation leaves out of the publication, then for what its descriptions record wrong. You check what the reviewers find and report it to the user, who guides what follows: the fixes and their commit. Read no doc, and of a publication only the places you check: this skill is the whole process. No need to `cd`: the scripts run by their path from the repository root, and each path is written from `<batch>`, as in `<batch>/<pmid>/curation.txt`.

## Environment

- `<batch>`: the batch directory the prompt names, in `<workdir>`, the curation's root directory, written as its absolute path (`realpath`), so that the `dir` each reviewer is sent is right from any directory. Its publications are those of `<batch>/pmids.txt` whose directory `<batch>/<pmid>/` holds `descriptions.jsonl` and `curation.txt`; the others are not reviewed.
- `<batch>/<pmid>/descriptions.jsonl`: the publication's curation, whole: one description per line, `{"pmid", "method", "accession1", "accession2", "start2", "stop2", "name2", "mappings1", "mappings2", "note"}`, `note` the description note.
- `<batch>/<pmid>/curation.txt`: the publication note, its first word the state, `CURATED`, or `SELECTED` when a relevant file could not be had.
- `<batch>/author.txt`: the curation's author, which names the batch's notes when it is committed.
- Drakkar, the database: the batch is written to it by its commit. A publication is **committed** when Drakkar holds its curation: its note there starts with this curation's, after the date and the batch's author. The user's message says which, or `uv run ./database/scripts/read.py sql "select pmid, state, left(annotation, 120) from associations where pmid in (…)"` shows it.
- **Commit** means, in this skill, always the commit of a batch's files to Drakkar by `./database/scripts/batch.py`. It never means git: the work directory is no git repository, and nothing of the review goes to git.

## Your role

The review is worth what the reviewers do: making them work well is your job. Read each reply critically. When one is suspicious (a part of the review skipped, a finding without its place in the publication, `nothing wrong` on a publication whose note names experiments it does not cover, a reply that misreads its task, a tool error), resume that reviewer (SendMessage) with a message that makes its task precise: what to look at again, and how. A finding stays its reviewer's: you check it, never replace the review by your own.

## Review

1. **Review**: one `reviewer` agent per publication, a few at a time, each started at xhigh effort, unless the user's message names another effort for this review, sent only `dir: <batch>/<pmid>`, `pmid: <pmid>`. It replies `<pmid>: nothing wrong`, or one line per wrong thing, those left out first: the pair or the fragment left out, or the description, then what is wrong, why, and where in the publication. Without a reply, run it once more; still without one, the publication is not reviewed.

2. **Check**: each wrong thing a reviewer reports, at the place in the publication it names, and at the place the curation's choice rests on, as the publication note or the description's note names it: true only when the publication proves the curation wrong, false otherwise. An ambiguous case is not wrong: where the publication supports the curation as well as the reviewer (its sources disagree, or it can be read either way), the curator has settled it, and the finding is false.

3. **Reply**: the publications reviewed and how many have nothing wrong; each wrong thing found true, with its publication, what it is about (the pair or the fragment left out, or the description), why and where; each found false, in one line with why; the publications not reviewed; the reviewers resumed, with why; from the agents' replies, the tool errors.

## Fixes

Only those the user asks for, as the user directs. A fix first corrects the publication's files in `<batch>/<pmid>/`: `descriptions.jsonl` stays its whole curation, as it should have been. What follows depends on whether the publication is committed.

**Not committed**: the corrected files are the curation. `curation.txt` and the description notes explain the corrected choices, as a curator's would. Then, as for the batch's curation:

1. **Merge**: `cat <batch>/*/descriptions.jsonl > <batch>/descriptions.jsonl`, then `uv run ./curation/scripts/notes.py <batch>`, which writes `<batch>/publications.jsonl` from the publications' `curation.txt`.
2. **Dry run**: `uv run ./database/scripts/batch.py <batch>` applies and checks everything in one transaction, then rolls it back; report its refused rows and errors as they are.
3. **Commit**, only when the user asks for it: `uv run ./database/scripts/batch.py <batch> --author "$(cat <batch>/author.txt)" --commit`.

**Committed**: Drakkar keeps every note it holds. A write adds a new version to a revised description and a new note on top of the publication's notes, dated by the write: so each fix writes only its own log (what it changes, why, where in the publication), never the whole note rewritten with the correction.

1. **Diff**: `uv run ./database/scripts/diff.py <pmid> <batch>/<pmid>/descriptions.jsonl` writes beside it what the corrected curation changes in Drakkar: `descriptions.add.jsonl`, the new descriptions, with their curation notes; `descriptions.revise.jsonl`, the revisions, each with its note, which you replace by its log, `FIXED: <summary>` then `- ` detail lines, the version before keeping the curation's note; `descriptions.delete.jsonl`, the removals, each with the note `REMOVED: not found by the curation`, whose reason you replace by the fix's.
2. **Log**: the publication's log, its first word the state, then what the fix changes and why, on top of `<batch>/<pmid>/curation.txt`, followed by a line `---`, so that the note there reads as Drakkar's.
3. **Merge**: `cat` the fixed publications' three diff files into `<batch>/descriptions.add.jsonl`, `<batch>/descriptions.revise.jsonl` and `<batch>/descriptions.delete.jsonl`, the first read in place of `<batch>/descriptions.jsonl`, and write `<batch>/publications.jsonl` with one line per fixed publication, its log only: `{"pmid": <pmid>, "state": "curated", "note": "CURATED\n…"}`, `selected` for a `SELECTED` log.
4. **Dry run**: `uv run ./database/scripts/batch.py <batch>`; report its refused rows and errors as they are.
5. **Commit**, only when the user asks for it: `uv run ./database/scripts/batch.py <batch> --commit`, with no author: the author of a curation is its original one, which its first note names.

After a fix, reply what each fixed publication's files now change, whether the dry run passes, else its refused rows and errors, and after a commit, its report. Never ask for the commit; when the user asks for it, commit without asking again.
