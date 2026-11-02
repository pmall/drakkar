---
name: export
disable-model-invocation: true
description: "The derived datasets exported from Drakkar: the run cut agreed with the user, the generic viral proteins of database/generic/ brought in step (new species placed, new generic names grouped), then the five datasets written as .tsv and .xlsx. Use when the user asks for a dataset export, or to update the generic viral proteins."
---

# Export

The derived datasets are files for other applications, exported from the live descriptions: the hh and vh descriptions, the sequences of the viral interactors, the human and viral mappings. The vh descriptions show each interaction as one human Swiss-Prot entry × one generic viral protein: one node of an interaction graph, one name in a species, from the files of `database/generic/`, which you bring in step with Drakkar before each export. Read no doc: this skill is the whole process. You write only the files of `database/generic/` and the export, never the database.

## The run cut

The export takes the vh runs up to a run, given by its ID (`runs.id`), never its name, and the special runs (`special-<n>`), all of them unless the user cuts them too; hh is always whole. Take the cut from the user's request; otherwise show the vh runs still being curated, with their publications neither curated nor discarded, and agree the cut with the user before going on:

```
uv run database-read sql "SELECT r.id, r.name, count(*) AS publications FROM runs AS r JOIN associations AS a ON a.run_id = r.id WHERE r.type = 'vh' AND a.state IN ('pending', 'selected') GROUP BY r.id, r.name ORDER BY r.id"
```

When the user asks only to update the generic viral proteins, skip this step and stop after the next one.

## The generic viral proteins

The files of `database/generic/`, tab-separated under a header line:

- `species.tsv`: `family_ncbi_taxon_id`, `ncbi_taxon_id`, `name`, `publications`. A species is an NCBI taxon treated as one virus. You write `ncbi_taxon_id` and `name`, the virus name readers use (`Epstein-Barr virus`, not the NCBI binomial *Lymphocryptovirus humangamma4*); the tool fills the others.
- `placed.tsv`: `ncbi_taxon_id`, `species_ncbi_taxon_id`, `name`: a taxon of viral interactors placed in its species, with its subtree: one missing from the NCBI taxonomy, or one the taxonomy keeps outside the species its virus is.
- `proteins.tsv`: `ncbi_taxon_id` (the species), `generic_name`, `protein`, `note`: each generic name of the dataset in its species, the label of the protein it is shown as, and why when it is not obvious.
- `README.md`: the folder, and why NCBI species were split, kept whole or placed.

The species of a viral interactor is given by the deepest taxon at or above its taxon in `species.tsv` (that taxon) or `placed.tsv` (the species it is placed in).

1. **Sync**: `uv run database-generic sync database/generic/`. It refreshes the families and publication counts, removes the names the dataset no longer has, adds the new ones with an empty `protein`, and prints what to decide. Run it again after each change: the files are in step when it prints `nothing`.

2. **Taxa**:

   One virus is one species, as one protein is one node.

   - `taxon under no species`, with its lineage up to its family and its names. A virus already listed, which the NCBI taxonomy keeps outside its species (an old species beside its successor, an unclassified taxon such as `Human bocavirus`): a line in `placed.tsv`, once its entries show which virus it is (`uv run database-read closest <sequence> --taxon <species ID>`, a sequence of `uv run database-read seq <accession>`). A new virus: a line in `species.tsv` for the taxon that is the virus, usually the NCBI species of the lineage. An NCBI species is split only where publications name its viruses apart, as `README.md` records (SARS-CoV-2 and SARS-CoV, each dengue serotype, each papillomavirus type); a new split or placement goes in `README.md`.
   - A taxon missing from the NCBI taxonomy (`not in the NCBI taxonomy`): a line in `placed.tsv`, its species found from its entries and its name (a strain of a listed virus).
   - `placed, now under its species in the NCBI taxonomy`: remove its line from `placed.tsv`.
   - `species not in the NCBI taxonomy`: the taxon left NCBI; its line takes the taxon that replaced it.

3. **Names with no protein**: the goal is an accurate network, where one viral protein is one node. For each new name, read the names of its species in `proteins.tsv` and decide, by what you know of the virus, whether it designates a protein the species already has: a spelling variant (`NS-1` and `NS1`), a synonym (an ORF name and a protein name: EBV `BPLF1` and `LTP`, KSHV `ORF37` and `SOX`), a prime form (`NS1'` with `NS1`). If so, it takes that protein; otherwise it is a new protein, and `protein` is the name. Group every name that should be grouped: a missed grouping is an acceptable error, never a default.

   - Within the species only.
   - A precursor and its cleaved parts are different proteins (`Gag` and `CA`, `NS2B-3` and `NS3`).
   - Case can tell two genes apart (EBV `BCRF1` and `BcRF1`).
   - What a name designates is judged from the name, and from its interactors when the name is ambiguous (vaccinia `F10` is on protein F8, which strain L-IPV names F10, not on the F10 kinase `VPK2`). A name on the wrong interactor is a curation error, corrected by curating its publication again, not here.
   - A group's `protein` is its label for the reader: the name its virus's field uses (`UL44` in HCMV, `BPLF1` in EBV), one of its names or not (`RT` for `p51-RT` and `p66-RT`). A label is kept from one export to the next.
   - `note`: why, on a line whose decision is not obvious (a synonym from another naming system, forms of one gene kept apart, a name judged from its interactors).

   Do your best for the best dataset at a reasonable cost: a few lookups when a name is unclear, not an exhaustive check.

   Evidence, read-only: `uv run database-read names <species ID>` (the generic names under the species, with their live descriptions and most used interactors), `uv run database-read entry <accession>` (gene names, chains, the generic names on the entry).

4. **`protein named elsewhere`**: a name's protein is a name of the species mapped to another protein; make the group's lines agree.

## The export

`uv run database-export database/generic/ <workdir>/exports/ --run <id>`, with `--special-run <id>` when the user cuts the special runs. Read-only on the database, it refuses to write anything while `database/generic/` is not in step. It writes five datasets, each as a `.tsv` and an `.xlsx` file named after the cut run (`descriptions_vh_run87.tsv`): `descriptions_hh`, `descriptions_vh`, `interactors_viral` (the sequence of each viral interactor), `mappings_h` and `mappings_v`; it prints the runs exported and the lines of each, then checks the files, read back, against each other and against the database: the numbers (live descriptions = exported + left out, a human interactor not up to date; mappings = lines + merged in homodimers), then `ok` or the failures, with an error.

## Reply

The generic viral proteins: what `sync` reported (counts, names removed); the species added or placed, and why; the names given another name's protein (`name → protein`, with their descriptions). Then the export: the run cut (name and ID), the special runs, the lines of each dataset, the numbers of the check and its result, and the directory. A failed check is the first thing said, with its failures. The user reviews `git diff database/generic/`; when a decision there changes, export again. Commit only on the user's request.
