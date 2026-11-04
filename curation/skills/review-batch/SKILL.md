---
name: review-batch
disable-model-invocation: true
description: "Review of a curated batch, committed or not: each publication reviewed by a reviewer agent, the wrong things it finds checked and reported to the user, who directs the fixes. The prompt names the batch."
---

# Review a batch

You review a curated batch: each publication is reviewed by a `reviewer` agent, which hunts in its descriptions and its note for what is wrong. You check what the reviewers find and report it. The review is optional and writes nothing: a batch is reviewed before or after its commit. Read no doc, and of a publication only the places step 3 checks: this skill is the whole process. Never `cd`, not even into a publication directory to start its reviewer: each reviewer starts in your current directory, and `uv run` finds the commands only from the directory you start in. Write each path from `<batch>` instead, as in `<batch>/<pmid>/curation.txt`.

1. **Batch**: `<batch>`, the batch directory the prompt names, in `<workdir>`, the curation's root directory. Its publications are those of `<batch>/pmids.txt` whose directory `<batch>/<pmid>/` holds `descriptions.jsonl` and `curation.txt`; the others are not reviewed.

2. **Review**: one `reviewer` agent per publication, a few at a time, sent only `dir: <batch>/<pmid>`, `pmid: <pmid>`. It replies `<pmid>: nothing wrong`, or one line per wrong thing: the description, what is wrong, why, and where in the publication. Without a reply, run it once more; still without one, the publication is not reviewed.

3. **Check**: each wrong thing a reviewer reports, at the place in the publication it names, and only there: true when the publication shows it, false otherwise.

4. **Reply**: the publications reviewed and how many have nothing wrong; each wrong thing found true, with its publication, its description, why and where; each found false, in one line with why; the publications not reviewed; from the agents' replies, the tool errors.

**Fixes**, only those the user asks for, as the user directs. A fix corrects the publication's `descriptions.jsonl` and says in its `curation.txt` what changed and why. A batch not committed is then merged and dry-run again: `cat <batch>/*/descriptions.jsonl > <batch>/descriptions.jsonl`, `uv run curation-notes <batch>`, then `uv run database-batch <batch>`, and committed only when the user asks: `uv run database-batch <batch> --author "$(cat <batch>/author.txt)" --commit`. A committed publication is corrected by a revision: `uv run database-diff <pmid> <file>` writes beside the corrected file what it changes.
