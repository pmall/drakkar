# Generic viral proteins

The species and the generic viral proteins of the vh descriptions dataset: one virus is one species, one viral protein is one node of the interaction graph ([`docs/datasets.md`](../docs/datasets.md#generic)).

The files, their columns and how a viral interactor finds its species are in [`generic.py`](../src/database/generic.py); before each export, the skill [`export`](../skills/export/SKILL.md) brings them in step with Drakkar and decides what is new. This file says why the species are what they are.

Names, ours: they are what the datasets show, and the NCBI scientific names are often ICTV binomials no reader uses (*Lymphocryptovirus humangamma4* is Epstein-Barr virus, *Orthoflavivirus zikaense* is Zika virus). Two species are in no NCBI family: Bacillus phage PBS2 and Clostridium botulinum D phage (unclassified *Caudoviricetes*).

## What was listed

The NCBI species, except where its species groups viruses that publications name apart:

- SARS-CoV-2 and SARS-CoV (with the bat SARS-like viruses) out of *Betacoronavirus pandemicum*.
- DENV-1 to DENV-4 out of *Orthoflavivirus denguei*.
- One per papillomavirus type (HPV16, HPV18, HPV8…), out of *Alphapapillomavirus* and *Betapapillomavirus*. The letter variants (HPV6a, HPV6b, HPV2a, HPV-5b) are listed on their own: NCBI puts them beside their type, not under it, so a list cannot fold them into it.
- EV-A71, CVA16, CVA10, CVA6, CVB1 to CVB5, poliovirus 1 to 3, CVA17, CVA24 out of *Enterovirus A*, *B* and *C*.
- TGEV, PRCV, feline and canine coronavirus out of *Alphacoronavirus 1*; HCoV-OC43, bovine and equine coronavirus out of *Betacoronavirus 1*; MHV and rat coronavirus out of *Betacoronavirus muris*; IBV and turkey coronavirus out of *Gammacoronavirus galli*.
- AAV1, AAV2, AAV4, AAV5, AAV6, AAV8, AAV9 and bovine AAV out of the *Dependoparvovirus* species.
- Murine norovirus out of *Norwalk virus*, avian erythroblastosis virus out of avian leukosis virus, PlxyMNPV out of AcMNPV.
- CVA8 out of *Enterovirus A*, AAV4 out of *Dependoparvovirus primate1*, as the viruses above them.
- Two viruses are listed on taxa the NCBI taxonomy leaves unclassified, their own species nowhere: BANAL-20-236, the SARS-CoV-2-related bat coronavirus of its spike entry (*unclassified Orthocoronavirinae*, 2730119), and Cardioderma bat coronavirus KY43 (*unclassified Alphacoronavirus*, 983922), kept apart from Cardioderma bat coronavirus (3119326, *unclassified Coronaviridae*), whose spike is 82.9 % identical to it.

Kept whole, where the NCBI species is the virus people name: influenza A (every subtype, every isolate), influenza B, HIV-1, HIV-2, HCV (every genotype), SIV (agm, cpz, mac, sm, stm), vaccinia (with rabbitpox and buffalopox), each adenovirus species (Ad2 and Ad5 together), rhinovirus A and C, FMDV (serotypes A and O), rotavirus A, Marburg (with Ravn), West Nile (with Kunjin), HEV (every genotype), and the herpesviruses with all their strains (EBV, HCMV, KSHV, HSV-1, HSV-2, VZV).

## Placed taxa

`placed.tsv` puts a taxon, with its subtree, in the species its virus is, where the NCBI taxonomy cannot:

- Missing from our NCBI dump, which lags behind UniProt: *Human herpesvirus 4* strain GD1 (3470597) is EBV. It resolves once the dump is refreshed, as NCBI has its parent; `sync` then says its line can go.
- *Hepacivirus C* (11103), the old NCBI species of HCV, kept beside its successor *Orthohepacivirus hominis*: hepatitis C virus.
- Unclassified taxa of a known virus, told by their entries: *Borna disease virus* (12455) is BoDV-1, *Mammalian orthobornavirus 1*; *Human immunodeficiency virus* (12721) is HIV-1 (its entry is HIV-1 protease); *Human bocavirus* (329641) is human bocavirus 1 (VP1 99.1 % identical to HBoV1's); *Reovirus sp.* (10891) is mammalian orthoreovirus (sigma-1 97.6 % identical to MRV-2's); *Rotavirus sp.* (10970) is rotavirus A (NSP1 99.0 % identical to strain A5-13's).
