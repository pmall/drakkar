"""Download the file at each URL, and convert it to text for the curation.

    uv run ./curation/scripts/download.py <dir> <url>...

It saves the file at each URL, whatever its size (a supplementary file the article links to, a
commercial construct's page or datasheet) in `<dir>` (the type from the response when its name gives
none), an archive unpacked (its videos left out), a document's images saved beside it, each file but
an image converted beside it, as `parse.py` does; a TIFF or a BMP image saved as PNG. Under a `#`
header, one line per file, starting with its URL: its entry, as in the manifest
(`curation/src/curation/fetch.py`), in JSON, its paths starting with `<dir>` (an image: `file`
alone), or why it could not be had (the HTTP outcome, not converted). An option the script does not
define is ignored, never refused.
"""

import argparse
from pathlib import Path

from curation.fetch import download

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("dir", type=Path)
parser.add_argument("urls", nargs="+")
args, _ = parser.parse_known_args()  # an option it does not define is ignored, never refused
lines = [f"{url}\t{line}" for url in args.urls for line in download(args.dir, url)]
print("\n".join(["#url\tmanifest entry, or why", *lines]))
