# Glossary

One meaning per word, used everywhere: docs, code, reports and conversations. When a schema name says otherwise, the glossary wins.

## Publications and their curation

| Term | Meaning |
| -- | -- |
| Publication | A PubMed record, identified by its PMID (`publications`). Never "paper". |
| Run | The PMIDs returned by one PubMed query (`runs`), of type vh or hh. Named by a number: "run 74" is its `name`, never its `id`. |
| vh, hh | Virus–human and human–human. A vh run looks for virus–human interactions, an hh run for human–human ones. hh gets no new curation, but its descriptions follow the invariants and the UniProt upgrades like vh ones. |
| Association | A publication in a run (`associations`). It carries the state and the note. A publication can be in a vh run and an hh run: two associations. |
| State | The curation state of an association: `pending` (not pre-curated), `selected` (kept at pre-curation, curation in progress), `discarded` (rejected at pre-curation), `curated` (all its relevant files explored and all its descriptions extracted; with or without descriptions). |
| Pre-curation | The decision `selected` or `discarded`, from the title and abstract. |
| Curation pass | Reading the relevant files of a selected publication (its full text and supplementary files) and recording its descriptions. Ends with the state `curated` when the curation could explore all of them and extracted all the descriptions; with a relevant file missing, `selected` with a date (`database.md#states`). The last AI curation pass is dated by `associations.ai_pass_at`. |
| Manual pass | The curation of a publication the AI curation could not curate fully (`selected` with a pass date): by hand, or by an agent from a curator file, an Excel file describing its interactions. |
| Note | The free text of an association (`associations.annotation`), the publication note: decisions about the publication (`database.md#notes`). It never holds maintenance information. |

## Proteins

| Term | Meaning |
| -- | -- |
| Protein | A UniProt entry, identified by its accession (e.g. `P04439`). Human or viral (`proteins.type` `h` or `v`). |
| Release | A UniProt release (e.g. `2021_02`). The latest one loaded in Drakkar is the current release. |
| Snapshot | A protein as it is in a release: one row of `proteins` (sequences, gene name, taxon). A protein has snapshots, never versions. The schema names `proteins.version` (the release a snapshot first appeared in) and `proteins_versions` are misnomers. |
| Strain | An NCBI taxon ID. A UniProt entry is usually associated with one strain. |
| Current snapshot | The snapshot of a protein in the current release (listed in `proteins_versions`). At most one per protein. |
| Obsolete snapshot | A snapshot that is not current: the protein changed since, or was deleted from UniProt. |
| Canonical sequence | The reference sequence of a snapshot, stored under its accession in `proteins.sequences`. Coordinates are positions on it. Its length is the length of the protein. |
| Isoform | Another sequence of the same snapshot, stored under its own accession (e.g. `P04439-2`) in `proteins.sequences`. |
| Gene name | The gene name of a human snapshot (`proteins.name`), e.g. `CCN1`. |
| Taxon | A node of the NCBI taxonomy (`taxon`). A snapshot has one (`proteins.ncbi_taxon_id`), which can be missing from the taxonomy when UniProt is ahead of NCBI. |
| Species | The NCBI taxon of rank species at or above a protein's taxon. For a viral protein: the virus. |
| Polyprotein | A viral protein cleaved into several mature proteins. |
| Mature protein | A part of a viral protein cleaved into several proteins (a polyprotein, or a protein cleaved into subunits), identified by the cleaved protein's accession and coordinates (e.g. DENV1 NS5 = `B5AGU1[2494-3392]`). |

## Descriptions

| Term | Meaning |
| -- | -- |
| Coordinates | The start and stop of an interactor on the canonical sequence of its snapshot, 1-based and inclusive. |
| Interactor | (accession, start, stop), reached through the snapshot it points to. |
| Human interactor | Always the full protein: coordinates 1 to the length. Named by its gene name (`name1`; in hh, `name2` too). |
| Viral interactor | A full viral protein or a mature protein (`protein2_id`, `start2`, `stop2` in vh). Named by its generic name (`name2`). |
| Generic name | The standard name of a viral interactor (e.g. `NS1`), independent of how UniProt or the publication names it. One viral interactor has one generic name, and in one protein a generic name names one viral interactor: (accession, start, stop) ↔ (accession, generic name). |
| Generic viral protein | A viral protein of the derived datasets: one node of an interaction graph, one name in a species, grouping the generic names of that species that make sense as a single viral protein (`datasets.md`). |
| Method | A PSI-MI interaction detection method (`methods`, e.g. `MI:0007`). |
| Description | One row of evidence: a publication × a method × a human interactor × a viral interactor (hh: two human interactors), with its mappings. This combination, (PMID, PSI-MI ID, interactor 1, interactor 2), is recorded once. Two mature proteins of the same cleaved protein are two interactors, so two descriptions. |
| Interaction | A human interactor × a viral interactor, whatever the publication and the method. One interaction can have many descriptions: that is the point of curation. |
| Mapping | A subsequence of an interactor that the experiment shows is enough for the interaction, on one side of a description (`mapping1` human, `mapping2` viral). It is recorded as the sequence the experiment used, aligned on the chosen entry but never adapted to it, even when that entry is of another strain. Its extra end residues, not on the interactor (an initiator methionine, a tag), are named in `nter` and `cter`. |
| Malformed mapping | A mapping whose JSON structure or types are wrong (e.g. numbers stored as text), whatever its content. Fixed in place, not by a revision. |
| Occurrence | Where a mapping, without its `nter` and `cter`, is found: an isoform, a start and stop, and an identity. On the canonical sequence, positions are relative to the interactor's coordinates; on other isoforms, to the whole isoform. Two occurrences on one isoform never overlap. Stored with the mapping, computed when the description is written. |
| Identity | The share of identical residues between a mapping and its occurrence: identical residues over the alignment length, i.e. the length of the mapping without its `nter` and `cter` plus the protein residues facing a gap inside it (the protein beyond both ends of the mapping does not count). A mapping written reaches 90 % on at least one occurrence, to tolerate strain differences; below, the write skips it. For `EY` descriptions, below 96 % is a warning. |
| Stable ID | The permanent identifier of a description (`EY…` from the web interface, `CW…` from Drakkar's writes). It never changes. |
| Version | One state of a description: rows with the same stable ID, numbered 1, 2, 3… A version is always a description version, never a protein one. |
| Live | The version of a description that is in use (`deleted_at` null). At most one per stable ID. |
| Revision | Writing a new version of a description: the live version is deleted and the new one created at the same instant. |
| Deleted version | A version with `deleted_at` set. It never counts: not in the datasets, not in the checks of live data. |
| Description note | The free text of a description version (`descriptions.annotation`): the curation's decisions on that version (`database.md#notes`). |
| Removed description | A stable ID whose last version is deleted, with no successor. Nothing is ever physically deleted. |
| Obsolete interactor | An interactor that points to an obsolete snapshot. Interactors go obsolete, not descriptions. |
| Obsolete description | A live description with at least one obsolete interactor. Not the same as deleted: an obsolete description is live and counts (its mappings feed the mappings dataset when its human target is up to date). |

## Checking

| Term | Meaning |
| -- | -- |
| Invariant | A rule the data must follow, with an ID (`database.md#invariants`). It is checked against the snapshots a description points to, whether current or obsolete. |
| Violation | A row that breaks an invariant, as reported by `database/scripts/check.py`. |
| Fix | The correction of an error found in the data, outside the regular process: a revision decided with the user (`database.md#versioning`). A malformed mapping is corrected in place, without a revision. |
| Upgrade job | Loading a new UniProt release and moving the obsolete interactors to current snapshots. |
| Versioning pass | The part of the upgrade job that moves the obsolete interactors of live descriptions to current snapshots, protein by protein. |
| Put aside | An obsolete interactor left on its old snapshot by a versioning pass because it needs a curation decision, with its reason. |
| Derived dataset | A dataset exported from Drakkar for other applications, built from live descriptions only (`database/src/database/export.py`). |
