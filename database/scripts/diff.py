"""Diff the descriptions of one publication, as curated, against its live descriptions in Drakkar.

    uv run ./database/scripts/diff.py <pmid> <file>

Read-only. The file holds descriptions to add (`database/src/database/files.py`), all of the
publication: the curation of the publication, whole. Matched with its live descriptions in its vh
run (`database/src/database/diff.py`), it writes beside the file what writing it would change:
`<name>.add.jsonl`, the descriptions to add; `<name>.revise.jsonl`, the descriptions to revise, as
`revise` rows; `<name>.delete.jsonl`, the descriptions to remove, as `remove` rows. Prints the
descriptions that stay the same, then the count and the path of each file. A file that cannot be
read, a publication in no vh run or a file of another publication: its message, exit code 1.
"""

import argparse
import sys
from pathlib import Path

from database.db import reading
from database.files import diff

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("pmid", type=int)
parser.add_argument("file", type=Path)
args = parser.parse_args()
try:
    with reading() as cur:
        print(diff(cur, args.pmid, args.file))
except ValueError as e:
    sys.exit(str(e))
