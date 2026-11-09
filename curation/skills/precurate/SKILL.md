---
name: precurate
disable-model-invocation: true
description: "Pre-curation of a run: its pending publications, each selected or discarded from its title and abstract by precurator agents, a slice of 50 each, merged into a publications file that passes the dry run, committed only when the user asks. The prompt names the run."
---

# Pre-curate a run

You pre-curate a run: each of its `pending` publications becomes `selected`, its full text to be curated, or `discarded`, from its title and abstract alone. `precurator` agents decide, a slice of 50 publications each; you check their files, merge them, dry-run and report. Read no publication and no doc: this skill is the whole process. No need to `cd`: the scripts run by their path from the repository root.

1. **Run**: `<run>`, the run's name as the prompt gives it, and its ID: `uv run ./database/scripts/read.py sql "SELECT r.id, count(*) FROM runs r JOIN associations a ON a.run_id = r.id WHERE r.type = 'vh' AND r.name = '<run>' AND a.state = 'pending' GROUP BY r.id"`, which gives `<ID>` and `<n>`, its pending publications. None pending: stop and say so. `<dir>`: `<workdir>/run<run>/precuration/`, `<workdir>` the curation's root directory, written as its absolute path (`realpath`).

2. **Author**: write it at once: `echo "claude-haiku-5-5 (precurator, $AI_AGENT, commit $(git rev-parse --short HEAD))" > <dir>/author.txt`.

3. **Pre-curate**: one `precurator` agent per slice, a few at a time: slice `<k>` holds the pending publications from offset `50 × <k>`, `<k>` from 0 while `50 × <k>` < `<n>`. Send each the instructions below, verbatim, `<ID>`, `<offset>` and `<file>` (`<dir>/<k>.jsonl`) filled in, and nothing else. The pending publications do not change before the commit, so a slice is the same each time it is read.

4. **Check**: every pending PMID once, in one file: `cat <dir>/[0-9]*.jsonl | jq -r .pmid | sort | uniq -d` (twice) and `comm -3 <(uv run ./database/scripts/abstracts.py <ID> 0 <n> | sed -n 's/^PMID //p' | sort) <(cat <dir>/[0-9]*.jsonl | jq -r .pmid | sort)` (missing or foreign). A slice whose file is missing, is not JSON Lines, misses a PMID or holds a foreign one: run its agent once more; still wrong, report it.

5. **Merge**: `cat <dir>/[0-9]*.jsonl > <dir>/publications.jsonl`, then the dry run: `uv run ./database/scripts/publications.py <dir>/publications.jsonl --author "$(cat <dir>/author.txt)"`. Refused rows: report them as they are.

6. **Reply**: whether the dry run passes, else its refused rows; the selected and discarded publications, counted; the discarded ones counted by reason (the words after `DISCARDED`, grouped by meaning); the slices run twice; from the agents' replies, the tool errors. Never ask for the commit.

**Commit**, only when the user asks for it: `uv run ./database/scripts/publications.py <dir>/publications.jsonl --author "$(cat <dir>/author.txt)" --commit` writes each publication's state and its note, after the date and the author.

## The instructions sent to each precurator

```
You pre-curate publications for Drakkar, a database of physical interactions between a viral
protein and a human protein, each shown by an experiment. From each publication's title and
abstract alone, you decide whether its full text is worth curating. No need to cd: run the
command from where you are.

1. Read your publications, once: uv run ./database/scripts/abstracts.py <ID> <offset> 50
   Each is a block: PMID, Types (its publication types), Title, Abstract (maybe empty).

2. Decide each one.

   SELECTED: an experiment of the publication could show a viral protein physically binding a
   human protein, by any method (co-immunoprecipitation, pull-down, two-hybrid, mass
   spectrometry of a complex, a screen, a structure, SPR, FRET...), even when the binding is
   not the main subject: a human protein restricting or helping a virus, a viral protein
   entering a human cell through a receptor, a viral protein acting on a named human protein
   (degrading, cleaving, targeting, activating, inhibiting, recruiting, relocalizing,
   modifying, hijacking it), as such an effect often rests on a binding the full text shows.
   The virus may infect any species, as long as the partner is human.

   DISCARDED, when the publication is only:
   - a review, an overview, a commentary, a guideline, a book chapter;
   - prediction: docking, molecular dynamics, in silico, machine learning, network
     pharmacology, bioinformatics;
   - a clinical, epidemiological, diagnostic, vaccine, public health or social study;
   - compounds, drugs or inhibitors, with no viral protein binding a human protein;
   - proteins of a non-human host (pig, chicken, fish, shrimp, insect, plant, bat, mouse...),
     no human protein tested;
   - viral proteins binding each other, or binding RNA, DNA, lipids or small molecules;
   - antibodies binding viral proteins: epitopes, neutralization, immune responses;
   - HLA proteins: antigen presentation;
   - a virus used as a tool (gene therapy vector, lentiviral delivery, oncolytic therapy, a
     viral promoter), or only mentioned, or "viral" in another sense;
   - changes of expression levels, pathway outputs or omics profiles, with no human protein
     named as a viral protein's partner or target.

   A publication without an abstract is decided on its title. When in doubt, SELECTED: never
   discard because the abstract lacks a detail, as the full text may show more.

3. Write <file> with the Write tool: one line per publication, in the order read, each PMID
   once, a JSON object with exactly these keys:
   {"pmid": 12345678, "state": "selected", "note": "SELECTED co-IP of NS1 with TRIM25"}
   {"pmid": 12345679, "state": "discarded", "note": "DISCARDED docking only"}
   state: selected or discarded. note: the state in capitals, then why in a few words: the
   proteins and the method for SELECTED, the reason for DISCARDED ("review", "clinical study",
   "porcine host proteins only", "antibody epitopes"). Inside a note, escape a double quote
   as \". Write no other file.

4. Reply with the numbers selected and discarded, and any error a command gave.
```
