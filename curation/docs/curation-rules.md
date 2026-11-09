# Curation rules

The biological rules of curation, explained: what is curated, and how each value of a description is identified. The curation applies them as the `curate` skill's prompt states them (`curation/skills/curate/SKILL.md`), their source of truth: a rule changes there and here. The method is the one published in the PNAS 2024 SI appendix (doi:10.1073/pnas.2308776121), with the alignment of a mapping brought to 90 % and its sources widened beyond the article.

## Principles

Every rule below derives from five principles, which also decide any case no rule decides:

1. Two proteins are considered to interact whenever an experiment detects an affinity between them.
2. The results are taken as the authors present them.
3. Each protein the experiment tested is assigned the UniProt entry that best represents it.
4. The sequences the experiment used are aligned as mappings on the assigned entry.
5. What the publication shows that the descriptions cannot hold is written in the notes.

## The publication

A publication is curated from its full text, with its supplementary files. What the authors present is taken with the thresholds they apply: a threshold is never guessed, nor recomputed from the methods or otherwise.

A supplementary file is relevant when it can hold interactions. Irrelevant, for instance: a video, a reporting summary, a peer review file, a checklist, a figure of non-interaction data, a file of raw source data whose values are already in a table that was read. A file that could not be read — not fetched, held by no copy, in a format that cannot be read — is judged relevant or not by what the text, its caption or its name show: a table of hits, a figure of an interaction experiment, data the text cites for an interaction.

A missing supplementary file is one the text cites and the files at hand lack. When it is relevant and the text gives its URL, it is downloaded before the curation is written. A relevant file that could not be had leaves the publication selected rather than curated, with the reason in its note (the Drakkar database's `database.md#states`).

## The experiment

The method must detect a physical interaction: binary methods (co-crystal, Y2H) and complex-detection methods (co-IP…). Never a method that shows colocalization, a functional interaction, or that cites an interaction shown elsewhere.

The method is a term of the PSI-MI interaction detection method branch (MI:0001). When no PSI-MI term describes the assay, the closest term of that branch is taken.

Any experiment in which the method detects the bait bound to the prey is evidence, even one designed to test something else: in an inhibition assay, the condition without the inhibitor. Any affinity an experiment shows between two proteins is an interaction, however weak. What the experiment adds without its being detected bound — an inhibitor, a competitor, a blocking peptide — is neither an interactor nor a mapping.

## The description

The scope is virus–human (vh) protein–protein interactions. A description involving an HLA protein (any `HLA-` gene) is not curated.

A description is a bait, a prey and the method that detected their binding, recorded once per publication × method × human interactor × viral interactor. Its mappings are the subsequences of the bait or the prey that the experiment shows are enough for the interaction. Every pair the publication shows is written: it is a description, or it is not kept because a criterion fails.

A description records what its publication demonstrates, never what is concluded from it: a mapping is never a region concluded from the results.

Each value — accessions, coordinates, generic names, mappings — is right: the publication determines it, with no doubt and no judgement call. Where no value can be right, because the publication does not determine it or its authors err or contradict themselves, a value that is not wrong is recorded instead: one the publication supports and that can be defended. Such a value is not an error. A value that was never verified is wrong.

Each value comes from the first tier that gives it, in the tier lists below, ordered from the most direct to the most inferred. The tier lists of the entry and of the mappings apply to human and viral interactors alike.

- A tier whose case does not apply, or that gives no value, passes to the next: a UniProt accession the publication gives that is not in the database passes to entry tier `reference`.
- A tier that would give a value the rules forbid — a human entry outside the Swiss-Prot human reference proteome, a TrEMBL entry where Swiss-Prot fits — gives no value, and passes to the next.
- When two sources of the publication disagree, the value of the earlier tier is used; within one tier, the curator chooses by judgement.
- When a tier leaves several values equally supported, and nothing in the publication breaks the tie, the curator chooses one that is not wrong.

## The interactors

Each interactor is a UniProt entry, of the current UniProt release in the database. A human interactor is always its whole protein. A viral interactor is a whole protein or a mature protein.

The interactor is what the experiment shows interacting, never its construct: a tag (GFP, FLAG, HA, GST fusions…) or a truncation leaves it the same, wild-type protein. When the publication names only a protein family or a complex (e.g. "Sec61", "14-3-3") where an experiment tested one protein, the interactor is the member the evidence points to: the construct, the primers, the antibody, the cited source.

The host protein must be human and wild type, and the viral protein wild type: this requires checking cell lines, plasmids, cDNA library origin, primers. Without evidence that the host protein is human and wild type, it is not kept. A changed residue anywhere in a protein's sequence, whatever the purpose of the change (a catalytically dead enzyme included), makes the protein not wild type. A natural post-translational modification — a phosphorylation, an acetylation, a glycosylation — changes no residue: the protein is still wild type.

A human interactor's entry is of the Swiss-Prot human reference proteome. A viral interactor's entry is the entry of the publication's strain, or the closest entry of the same virus when UniProt does not have the strain's entry: an entry of another virus, however close its sequence, is wrong. When the entry is of another strain than the publication's, the publication's strain is written in the description note. Swiss-Prot is preferred to TrEMBL whenever both fit. Between an entry built in a laboratory — a fusion with a reporter, a chimera of two strains — and a natural protein's entry, the natural one is taken whenever it fits.

Entry tiers:

1. `accession`: when the publication gives a UniProt accession, its current entry.
2. `reference`: when the publication gives another identifier or a name — a GenBank, RefSeq or PDB accession, a clone, a plasmid, a commercial construct, a human gene name, a viral protein with its strain — the current entry it designates.
3. `sequence`: when the protein's sequence is known, from the publication or another database (e.g. the GenBank record of a strain UniProt does not have), the current entry closest to it by sequence, of the same virus for a viral protein. The whole sequence of the protein is aligned, never a part of it such as a mapping.
4. `virus`: when the strain of a viral protein is not given and its sequence is not known, the Swiss-Prot entry of the virus for that protein, otherwise the entry most used in the database for that virus and generic name.
5. `best-effort`: in any other case, any way possible.

With no entry even at tier `best-effort`, UniProt having the protein of no strain of that virus, the pair is not kept: the human identifier comes from the Swiss-Prot human reference proteome, and the viral protein is identified in UniProt.

In a high-throughput publication, an exception to the tier order: the entry is assigned from the rawest data available (e.g. ORF sequences), by alignment.

## The generic name

A viral interactor's generic name is the standard name of the protein the publication tested, as the database already names it: that protein's existing name is reused rather than the publication's spelling (`orf6`, not `orf-6`; all "non-structural protein 1" variants → `NS1`). The names used in the database are followed for the strain, then the virus, then the family. A new protein is named in the form its neighbours use.

On one snapshot of an entry, one generic name per region and one region per generic name: this is enforced. Across the strains of a virus, the same generic name is used when it can be: this is not enforced.

## The mature protein

A mature protein is an interactor with coordinates, cleaved from a polyprotein (DENV1 NS5 = `B5AGU1[2494-3392]`) or from a protein cleaved into subunits (SARS-CoV-2 S1 = `P0DTC2[14-685]`, influenza HA2 = `Q8QPL1[347-568]`): the entry of the protein it is cleaved from, with the start and stop of the mature protein on it. Two mature proteins of one cleaved protein are two interactors. A mature protein always takes precedence over a mapping.

Coordinates tiers:

1. `publication`, for viral mature proteins only: the boundaries the publication gives, only when the entry has the sequence the publication used (same strain or clone; a shift in numbering is corrected).
2. `annotation`: when the entry has a chain, peptide or propeptide feature for the mature protein, that feature.
3. `database`: when the database already records a span for that entry and that generic name, that span.
4. `GenBank`: when the entry's GenBank or RefSeq record has a mature peptide feature for the mature protein, that feature.
5. `best-effort`: in any other case, any way possible, for instance the chain of another strain's entry, carried over by alignment.

## The mapping <a id="mapping"></a>

The interactor is identified first — the whole protein, or the mature protein the mapping belongs to — then the mapping within it: the part of the interactor the bait or prey construct carried.

A mapping is a strict subsequence of its interactor, never the whole of it, except when a publication tests many lineages of one protein, none with its own UniProt entry: one entry is chosen for all of them, and each lineage's full-length sequence is a mapping. A mapping is at least 4 residues. A peptide of 20 residues or less is a mapping like any other, and easy to miss.

A mapping belongs to one side of one description, so to its method. A description holds every mapping its publication shows, several per side if so. A mapping across a cleavage site, which the data model cannot record, goes in the publication note.

A mapping is the sequence used in the experiment, or as close to it as possible, never adapted to UniProt: the downstream work uses these sequences.

Mapping tiers:

1. `written`: when the publication writes the sequence, in its text, a figure, a table or a supplementary file, that sequence.
2. `coordinates`: when the publication gives coordinates on its own sequence (its strain, its clone), the subsequence at those coordinates, from UniProt or another database.
3. `other-numbering`: when the publication gives coordinates on another sequence it names (a reference strain, a numbering it states), the region they designate on that sequence, carried over to the publication's sequence when it is known, otherwise the subsequence of that other sequence.
4. `construct`: when the publication names a construct without coordinates — a deletion mutant, primers, a commercial or deposited construct, a construct of a cited publication — the subsequence of the publication's sequence within the boundaries the construct's own record gives: the primers, the supplier, the plasmid record, the cited publication.
5. `best-effort`: in any other case, any way possible that gives the sequence the construct carried.

A mapping's residues that are not on its interactor are kept: a tag, a linker, or the protein's own residues outside the interactor, such as the initiator methionine before a mature protein or residues of the cleaved protein past its end. These extra end residues are named `nter` (at the mapping's start) and `cter` (at its end).

A mapping must reach 90 % identity on its entry, which tolerates the differences between strains, UniProt holding few of them. One below 90 % is not kept, and is a curation smell: a sign of an error in the mapping or in the chosen entry, to look at again.
