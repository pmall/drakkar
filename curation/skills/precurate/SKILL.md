---
name: precurate
disable-model-invocation: true
description: "Pre-curation of a run: its pending publications written in batches of titles and abstracts, each batch decided by a precurator agent, merged into a publications file that passes the dry run, committed only when the user asks. The prompt names the run and may set the batch size."
---

# Pre-curate a run

You pre-curate a run: each of its `pending` publications becomes `selected`, its full text to be curated, or `discarded`, from its title and abstract alone. You write the titles and abstracts in batches, a `precurator` agent decides each batch, and you check their files, merge them, dry-run and report. Read no publication and no doc: this skill is the whole process. No need to `cd`: the scripts run by their path from the repository root.

1. **Run**: `<run>`, the run's name as the prompt gives it, and its ID: `uv run ./database/scripts/read.py sql "SELECT r.id, count(*) FROM runs r JOIN associations a ON a.run_id = r.id WHERE r.type = 'vh' AND r.name = '<run>' AND a.state = 'pending' GROUP BY r.id"`, which gives `<ID>` and `<n>`, its pending publications. None pending: stop and say so. `<dir>`: `<workdir>/run<run>/precuration/`, `<workdir>` the curation's root directory, written as its absolute path (`realpath`). `<size>`: the batch size, 50 by default.

2. **Batches**: batch `<k>`, from 0 while `<size> × <k>` < `<n>`, holds the pending publications from offset `<size> × <k>`: `uv run ./database/scripts/abstracts.py <ID> <offset> <size> > <dir>/<k>.txt`, every batch in one loop. Each publication is a block of four lines, `PMID`, `Types`, `Title`, `Abstract`. The pending publications do not change before the commit.

3. **Pre-curate**: one `precurator` agent per batch, a few at a time, sent only `input: <dir>/<k>.txt`, `output: <dir>/<k>.jsonl`. It writes its output file and replies the tool errors.

4. **Check**: the outputs hold every PMID of the inputs once, and no other:

   - `grep -h '^PMID' <dir>/[0-9]*.txt | cut -d' ' -f2 | sort > <dir>/pmids.in`
   - `jq -r .pmid <dir>/[0-9]*.jsonl | sort > <dir>/pmids.out`, which names an output that is not JSON Lines
   - `diff <dir>/pmids.in <dir>/pmids.out`, each line a PMID missing, foreign or twice; `grep -l <pmid> <dir>/[0-9]*` gives its batch.

   A batch whose output is missing, invalid or wrong: run its agent once more; still wrong, report it.

5. **Merge**: `cat <dir>/[0-9]*.jsonl > <dir>/publications.jsonl`, then the dry run: `uv run ./database/scripts/publications.py <dir>/publications.jsonl`. Refused rows: report them as they are.

6. **Reply**: whether the dry run passes, else its refused rows; the selected and discarded publications, counted, and among the selected those in doubt (`in doubt:` in their note); the discarded ones counted by reason (the words after `DISCARDED`, grouped by meaning); the batches run twice; from the agents' replies, the tool errors. Never ask for the commit.

**Commit**, only when the user asks for it: `uv run ./database/scripts/publications.py <dir>/publications.jsonl --commit` writes each publication's state and its note, after its date.
