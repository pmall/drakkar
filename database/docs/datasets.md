# Derived datasets

Terms are defined in `glossary.md`.

Drakkar is the curation database. Derived datasets are exported from it for other applications. This document gives what they mean for curation.

## Drakkar is consistent at the UniProt entry level

Each description is exact on its UniProt entries, whatever their version: the snapshot it points to keeps the interactions and the mappings as they were recorded at the time of curation. Drakkar does not reconcile entries or strains: the derived datasets do, when they need to. What each dataset holds, its files and its columns are in `database/scripts/export.py`.

## Generic viral proteins <a id="generic"></a>

The vh descriptions dataset gives generic interactions: one human Swiss-Prot entry with one generic viral protein. This is the only goal of the generic viral proteins: a generic viral protein is what makes sense to show as a single viral protein, one node of an interaction graph. Whether two viral interactors are exactly the same protein does not matter: `NS1'`, the frameshift extension of `NS1`, is the same node as `NS1`.

A generic viral protein is one name in a species. It groups the generic names that designate it across the strains and entries of the species, in the descriptions of the vh descriptions dataset: its spelling variants (`NS-1`, `NS1`) and its synonyms (`orf14`, `orf9c`; EBV `BPLF1`, the ORF, and `LTP`, the protein). It is grouped by judgment, within one species, from what each name designates; the interactors a name is on help to tell when the name is ambiguous (vaccinia `F10` is curated on protein F8, which strain L-IPV names F10, not on the F10 kinase `VPK2`). A precursor and its cleaved parts are different proteins (`Gag` and `CA`, `NS2B-3` and `NS3`). Case can tell two genes apart (EBV `BCRF1` and `BcRF1`).

The goal is an accurate network: one viral protein, one node. Two nodes for one protein is an acceptable error, but every name that should be grouped is grouped: the best dataset at a reasonable cost, not zero mistakes. Each group has a label for the reader, the name its virus's field uses (`UL44` in HCMV, `BPLF1` in EBV, `RT` for `p51-RT` and `p66-RT`), kept from one export to the next; a note explains a decision that is not obvious. The species, the taxa each treated as one virus, and the generic viral proteins are the files of `database/generic/` (`database/src/database/generic.py`).

This is second-order curation, a grouping, not a curation of the descriptions: it takes the generic names as the curator set them and never changes a description. Putting the right name on the right viral interactor is the curator's job; a wrong name is a curation error, corrected by curating its publication again, never here.

The mappings are not grouped: the mappings datasets keep the exact source of each mapping, its entry, strain and isoform.

## What it means for curation

- Every UniProt upgrade works on all the obsolete interactors: each one is moved to the latest snapshot it can be on, a human one whenever it can be (the versioning pass).
- A description with an obsolete interactor is live and counts: it was right on its snapshots when it was curated; when a viral protein is gone from UniProt (e.g. a patient isolate), it stays live on its old snapshot, and its mappings stay good data.
