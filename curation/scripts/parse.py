"""Convert full texts and supplementary files to the texts a curation reads, short in tokens.

    uv run ./curation/scripts/parse.py <dir> <file>...

Converts each file, a path relative to `<dir>` (the publication directory), by its type, to texts
written beside it and named by their format. No network. The conversions are described in
`curation/src/curation/parse.py`.

Each file is first made ready to read, as `fetch.py` makes the downloads (`prepare`): a TIFF or a
BMP image replaced by its PNG, a document's images saved beside it. Prints the entries of the
manifest (`curation/src/curation/fetch.py`) of each file, then of its images, one JSON line each,
paths relative to `<dir>`: `file`, then `text` and `bytes`, or `sheets`, each with `sheet`, `text`
and `bytes`. An image has its `file` alone; so has a file that cannot be converted (a scanned PDF, a
damaged file, a type with no converter), why on stderr, nothing written for it. A file that does not
exist is refused. The exit code is 1 when a file is not converted.
"""

import argparse
import json
import sys
from pathlib import Path

from curation.parse import ParseError, entries

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("dir", type=Path)
parser.add_argument("files", nargs="+", metavar="file")
args = parser.parse_args()
refused = False
for file in args.files:
    try:
        found = entries(args.dir, file)
    except ParseError as e:
        print(f"{file}: not converted, {e}", file=sys.stderr)
        refused = True
        continue
    for x in found:
        if why := x.pop("not_converted", None):
            print(f"{x['file']}: not converted, {why}", file=sys.stderr)
            refused = True
        print(json.dumps(x, ensure_ascii=False))
sys.exit(1 if refused else 0)
