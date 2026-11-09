"""The derived datasets (`database/docs/datasets.md`), exported from Drakkar (read-only on the
database).

    uv run ./database/scripts/export.py <generic> <dir> [--run <id>]

Writes the five datasets to the directory, from the live descriptions whose human interactors are
on their current snapshots, in Swiss-Prot: of the vh runs up to `--run`, all by default; of every
hh run. A run is given by its ID (`runs.id`), not its name, so that an export can stop before a
run in progress; a cut that is not the ID of a vh run is refused. The species and generic viral
proteins are read from `<generic>`, the directory of their files
(`database/src/database/generic.py`), in step with Drakkar: a taxon under no species, a species not
in `species.tsv` or a name with no protein is reported, and nothing is written.

Each dataset is written as a `.tsv` file, tab-separated under a header line, and an `.xlsx` file,
the same lines; each name ends with `run` and the name of the last vh run exported by ID, each
character other than a letter, a digit or `-` made a `-`
(`descriptions_vh_run87.tsv`). A description's stable ID is given after its type, `HH:EY12AB34CD`
or `VH:CW12AB34CD`: a stable ID is unique within its type only.

- `descriptions_hh`: `stable_id`, `version`, `pmid`, `psimi_id`, `method`; each human interactor:
  `release1` (the release its snapshot first appeared in), `accession1`, `gene_name1`, then
  `release2`, `accession2`, `gene_name2`. One line per description, sorted by stable ID.
- `descriptions_vh`: `stable_id`, `version`, `pmid`, `psimi_id`, `method`; the human interactor:
  `release1` (the release its snapshot first appeared in), `accession1`, `gene_name1`; the viral
  interactor, on any snapshot, from the most general to the most specific:
  `species_ncbi_taxon_id`, `species`, `protein` (from `<generic>`), `strain_ncbi_taxon_id`,
  `strain` (its scientific name, empty when the taxon is missing from the NCBI taxonomy),
  `release2`, `accession2`, `uniprot_name2` (the UniProt protein name), `generic_name2`,
  `start2`, `stop2`. One line per description, sorted by stable ID.
- `interactors_viral`: `release`, `accession`, `start`, `stop`, `sequence` (the canonical
  sequence from start to stop): one line per viral interactor of `descriptions_vh` (`release2`,
  `accession2`, `start2`, `stop2`), sorted by its columns. The snapshot of an entry gone from
  UniProt can be read nowhere else.
- `mappings_h`: `stable_id`, `sequence` (as the experiment used it, its extra end residues
  included, in lowercase: `mSTNPK`), the interactor: `release`, `accession`; `isoform` (the
  isoform it is found on: the canonical one, the accession, when the mapping occurs on it, else
  its other isoform with the lowest number), `target` (`h` or `v`, the kind of the other
  interactor), `nter`, `cter` (the extra end residues, mostly empty). The mappings of the human
  interactors of `descriptions_hh` (both sides) and `descriptions_vh`, one line per (stable ID,
  sequence, isoform): a homodimer's mapping on both sides is one line. Sorted by its columns.
- `mappings_v`: `stable_id`, `sequence`, the interactor: `release`, `accession`, `start`, `stop`;
  `isoform`, `nter`, `cter`, as in `mappings_h`: the mappings of the viral interactors of
  `descriptions_vh`. Sorted by its columns.

Prints the runs exported and the lines of each dataset, then checks the `.tsv` files, read back
(`check_export`): each description on one line in one file; the viral interactors of
`descriptions_vh`, each on one line of `interactors_viral`, its sequence as long as its
coordinates; each mapping on one line, on an interactor of its description, in the file of its
target; and the numbers, each from its own query: the live descriptions of the runs exported,
those exported and those left out (a human interactor not up to date); the mappings of the
descriptions exported, the lines written and those merged in homodimers. It ends with `ok`, or
with the failures and an error, the files left for a look.
"""

import argparse
import sys
from pathlib import Path

from database.db import reading
from database.export import export

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("generic", type=Path)
parser.add_argument("directory", type=Path)
parser.add_argument("--run", type=int)
args = parser.parse_args()
try:
    with reading("60s") as cur:
        print(export(cur, args.generic, args.directory, args.run))
except ValueError as e:  # a cut that is no vh run, generic files not in step, a check that fails
    sys.exit(str(e))
