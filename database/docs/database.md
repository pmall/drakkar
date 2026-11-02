# Drakkar database: structure, versioning and invariants

Drakkar is the curation database (PostgreSQL, schema `public`); Vinland, the published database, is rebuilt from it at each release.

Its whole structure (tables, constraints, indexes, rules, the `dataset` view) is `database/sql/schema.sql`, written from the database by `database/tests/build_fixture.py`, never by hand: run it again after every change of structure. The tests build their database from it.

## Tables <a id="tables"></a>

| Table | Role |
| -- | -- |
| `runs` | The PMIDs of one PubMed query (`type` `vh` or `hh`, `name` = sequence number), or a special run (vh, `special-<n>`). New runs are `vh`. |
| `publications` | One row per PMID, with the PubMed record as JSON in `metadata`. |
| `associations` | A publication in a run: its `state`, its publication note (`annotation`) and the date of its last AI curation pass (`ai_pass_at`): its states (`#states`). |
| `descriptions` | Descriptions, versioned (`#versioning`), each version with its description note (`annotation`, `#notes`). |
| `methods` | The PSI-MI ontology, never modified: a missing term is reported to the user. Each term has its `synonyms` and `is_detection`, true for the interaction detection methods (under MI:0001), both from the PSI-MI file. |
| `proteins` | One row per snapshot of a UniProt entry (`#uniprot`). |
| `proteins_versions` | The current snapshots, with their gene names, synonyms, features (chains, peptides), whether the entry is in Swiss-Prot (`reviewed`) and its secondary accessions (old accessions UniProt merged into it), from the UniProt release; `search`, its accession, names, taxon and protein name in one text, trigram-indexed. |
| `taxon`, `taxon_name` | The NCBI taxonomy. It can lag behind UniProt: a snapshot's taxon can be missing from it (R3). `taxon.search`: all the names of a taxon in one text, trigram-indexed. |
| `dataset` | A materialized view joining everything, one row per description version, for consultation and exports only. Its readers expect its columns, their order and types. A snapshot whose taxon is missing from `taxon` keeps its rows, with taxon name `Obsolete`. Its unique index on `description_id` allows `REFRESH MATERIALIZED VIEW CONCURRENTLY`. |

### States <a id="states"></a>

A publication of a vh run moves through these states, its association's `state` and `ai_pass_at`:

| State + `ai_pass_at` | Meaning |
| -- | -- |
| `pending` | Not pre-curated yet: every publication of a new run starts there. |
| `selected`, null | Kept at pre-curation, from its title and abstract: waiting for its AI curation pass. |
| `selected`, date | The AI curation could not curate it fully, a relevant file missing: waiting for a manual pass, in a special run. |
| `curated` | All its relevant files explored and all its descriptions extracted, with or without descriptions (by the AI curation if dated). |
| `discarded` | Rejected at pre-curation. |

A run is **complete** when every publication is `discarded` or `curated`. The AI curation is **done with a run** when no publication is `pending` and every `selected` publication has a date. The publications left `selected` with a date are moved, when the user asks, to the open special run, the highest `special-<n>`, so the run they leave can be complete: the association changes run, its descriptions with it, and a `Moved` note goes first in its note (`#notes`); a new special run is opened when the user says so. A `discarded` publication without an AI curation note may have been decided on the abstract or on the full text: the two cannot be told apart, and such states are left as they are.

### Notes <a id="notes"></a>

The notes only serve the curation to explain and justify its choices later, to an external reviewer or in a report: free text.

- **Publication note**, `associations.annotation`: the notes of the publication, the newest first, each followed by a line `---` and the previous ones. A curation pass writes its note, its first word the state, which the write puts after the date and, when the write names one, its author (`[2026-10-06] CURATED …`, `[2026-10-06, pmall] CURATED …`); a move to a special run writes the note `Moved from run <name>`, dated the same way.
- **Description note**, `descriptions.annotation`, one note per version, undated: the version has its dates. A version made by a curation holds the curation's note. A version made otherwise, and what was decided on a version later without a new version (an interactor not moved, an in-place correction, a removal), are each a line `ACTION: summary` followed by `- ` detail lines. The history of a description is its notes read version by version.

| Action | Why | Example summary |
| -- | -- | -- |
| `UPDATED` | A UniProt release: an interactor moved to its new snapshot (a new version), or kept on its old one, or an isoform renamed (in place) | `UniProt 2026_03, Q77YF9 → P12520 (deleted; NL4-3 Vpr), 1–78 → 1–96`, `UniProt 2026_03, side 2 B0FAN5 not moved: deleted, patient isolate, no strain in the publication` |
| `FIXED` | An error found in Drakkar | `name1 AES → TLE5, gene name of the snapshot` |
| `REMOVED` | The end of a description, in place on its last version, with its reason | `HLA protein`, `not found by the curation` |

A publication note:

```
[2026-10-21] Moved from run 88
---
[2026-10-20] SELECTED
- Table S2, the screen's hits (Results, "Screen"), could not be had: no URL given
---
Y2H, see table S2
```

## Descriptions and versioning <a id="versioning"></a>

- A description: `association_id` (publication), `method_id`, human interactor (`protein1_id`, `start1`, `stop1`, `name1`), viral interactor (`protein2_id`, `start2`, `stop2`, `name2` = generic name), `mapping1/2` (mapped sequences with their occurrences on each isoform, JSON).
- An interactor is (accession, start, stop); the accession is reached through `proteins.id`, which points to one snapshot of the entry.
- **Nothing is ever deleted.** A revision deletes the live version (`deleted_at`) and inserts the next version under the same stable ID at the same instant; a removal deletes the live version with no successor. A stable ID never changes and keeps its publication (V6); uniqueness (D5) applies to live versions only.
- **Errors in the data** (invariant violations) should not happen: every write is checked. An error found anyway is fixed outside the regular process, decided with the user: a fix corrects a description against its own snapshots, never moves it to another snapshot (that is the versioning pass), and goes through `database-revise` with a `FIXED` note. A malformed mapping (D11) is corrected in place, without a revision, on every version that has it: its values stay the same and nothing else in the row changes.
- **Writes**: descriptions and publication states are written only by the write commands, which check each row and every invariant (`#invariants`) on the result before they commit. What each write checks, derives and refuses is in `database/src/database/write.py`, its files in `files.py`.
- Moving an interactor to the current snapshot of the same accession is the versioning pass, not a revision.

## UniProt versioning <a id="uniprot"></a>

### Model

- `proteins` holds one row per **snapshot** (accession, `version`, name, description, taxon, canonical and isoform sequences in `sequences`). `version` is the release in which the snapshot **first appeared**. Descriptions point to `proteins.id`.
- `proteins_versions` lists the current snapshots: one per accession of the latest release (`current_version`), keyed by (accession, version). A snapshot absent from it is **obsolete**.
- `proteins` only grows: each release adds a snapshot per new or changed entry, and an unchanged entry keeps its snapshot.

### Releases

A release is loaded by its commands, the NCBI taxonomy first, then UniProt: `database/src/database/taxonomy.py`, and `uniprot.py`, which says when an entry keeps its snapshot. UniProt keeps only Swiss-Prot and the TrEMBL entries of reference proteomes: human Swiss-Prot entries are mostly updated in place, viral entries used by descriptions are often deleted. An entry whose taxon is missing from the taxonomy is imported, and the taxon is not added (R3). The descriptions on a snapshot that becomes obsolete are left to the versioning pass.

**An accession can have several snapshots, and several obsolete ones**: one per release where its entry changed. Different descriptions, or different versions of one description, can use different snapshots of the same accession. So any comparison about a description (sequence, length, gene name, taxon) uses the snapshot the description points to (`protein1_id`, `protein2_id`), never "the latest old snapshot" of the accession. Example: a protein with an older, longer snapshot used by a live description and a later, shorter one: comparing the later one with another entry can wrongly say "same sequence".

After a versioning pass, the obsolete snapshots that no description row references (live or deleted) are deleted. A snapshot used by a deleted version is kept, so that the history of a description can be read; current snapshots are never deleted.

## Invariants <a id="invariants"></a>

Checked by `database-check` (`database/src/database/check.py`) and inside every write (`#versioning`). Scope: vh and hh. "Live" = `deleted_at IS NULL`. Severity: **error** = must never happen; **warning** = needs a look; **upgrade** = an obsolete interactor, left to the versioning pass; **info** = good to know. Invariants judge a description against the snapshots it points to, current or obsolete. The method chosen is not checked.

| ID | Invariant | Severity |
| -- | -- | -- |
| R3 | Proteins of live descriptions whose taxon is not in `taxon`: a mismatch between UniProt and the NCBI taxonomy, not an error on our side; the `dataset` view lists such descriptions anyway, a question of reading the dataset, not of curation. | info |
| V2 | Versions of a stable ID are contiguous from 1. | error |
| V3 | At most one live row per stable ID, and it is the highest version. | error |
| V4 | Each non-last version is deleted, no later than the next version's creation. | error |
| V5 | `deleted_at` is not before `created_at`. | error |
| V6 | All versions of a stable ID belong to the same publication. | error |
| V7 | Stable ID format: `EY` or `CW` + 8 uppercase hexadecimal characters; `EYUW` + 6 for a bulk import of hh descriptions. | error |
| D1 | Protein 1 is human; protein 2 is viral in vh, human in hh. | error |
| D2 | Both proteins are current snapshots (latest UniProt release). | upgrade |
| D3 | Viral interactors: 1 ≤ start ≤ stop ≤ canonical length (the coordinates of the mature protein). | error |
| D4 | Human interactors are the full protein: start = 1 and stop = canonical length, the only rule for their coordinates. | error |
| D5 | One live description per (publication, method, interactor 1, interactor 2). | error |
| D6 | One non-empty generic name per viral interactor. | error |
| D7 | Human names (`name1`, and `name2` in hh) are the gene name of their snapshot. | warning |
| D9 | Mapping content: an uppercase amino acid sequence, once per side, its `nter` and `cter` (when present, not empty) at its ends, with at least one occurrence. Each stored occurrence is judged on its own, against the protein segment at its coordinates, on the mapping without its `nter` and `cter`: an occurrence recorded at 100 % is exactly the mapping; otherwise the mapping aligned end to end on the segment is no more than 1 point below the recorded identity (gap placement can differ). No identity threshold: low identities are D12 warnings. Whether the mapping could also be found elsewhere or on other isoforms is not checked. Text numbers are read as numbers. | error |
| D10 | One viral interactor (start, stop) per generic name of a viral snapshot (`protein2_id`, generic name): the converse of D6. Grouped by snapshot, not accession: coordinates on different snapshots are not comparable (Vpu P05919: 1–81 is the whole old protein, 1–82 the whole new one). | error |
| D11 | Mapping structure, not content, on every version (live or deleted): a list of objects `{sequence: string, nter: string, cter: string, isoforms: [{accession: string, occurrences: [{start, stop, identity: numbers}]}]}`, `nter` and `cter` optional. Bad structure or bad types, e.g. numbers stored as text, fixed in place without a revision (`#versioning`). | error |
| D12 | Mapping identity: the best occurrence of a mapping is below 96 % (`EY` descriptions) or 90 % (`CW`). | warning |
| S1 | A publication with a live description is `selected` (curation in progress) or `curated` (done, with or without descriptions). | error |
| S5 | Run names are unique. | error |
