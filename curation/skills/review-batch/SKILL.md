---
name: review-batch
disable-model-invocation: true
description: "Review of a curated batch: each publication reviewed by a reviewer agent, the wrong things it finds checked and reported to the user, who directs the fixes. The prompt names the batch."
---

# Review a batch

You review a curated batch: each publication is reviewed by a `reviewer` agent, which looks for what the curation leaves out of the publication, then for what its descriptions record wrong. You check what the reviewers find and report it. The review is optional, and it is all you do: it writes nothing, and the user directs the fixes and the commit. Never check whether the batch is committed. Read no doc, and of a publication only the places step 3 checks: this skill is the whole process. Never `cd`, not even into a publication directory to start its reviewer: each reviewer starts in your current directory, and `uv run` finds the commands only from the directory you start in. Write each path from `<batch>` instead, as in `<batch>/<pmid>/curation.txt`.

1. **Batch**: `<batch>`, the batch directory the prompt names, in `<workdir>`, the curation's root directory. Its publications are those of `<batch>/pmids.txt` whose directory `<batch>/<pmid>/` holds `descriptions.jsonl` and `curation.txt`; the others are not reviewed.

2. **Review**: one `reviewer` agent per publication, a few at a time, each started at high effort, unless the user's message names another effort for this review, sent only `dir: <batch>/<pmid>`, `pmid: <pmid>`. It replies `<pmid>: nothing wrong`, or one line per wrong thing, those left out first: the pair or the fragment left out, or the description, then what is wrong, why, and where in the publication. Without a reply, run it once more; still without one, the publication is not reviewed.

3. **Check**: each wrong thing a reviewer reports, at the place in the publication it names, and only there: true when the publication shows it, false otherwise.

4. **Reply**: the publications reviewed and how many have nothing wrong; each wrong thing found true, with its publication, what it is about (the pair or the fragment left out, or the description), why and where; each found false, in one line with why; the publications not reviewed; from the agents' replies, the tool errors.
