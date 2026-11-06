"""Download the full text of a publication, as published, with its supplementary files, and
convert them to text for the curation.

    uv run ./curation/scripts/fetch.py <dir> <pmid>

The routes it tries, the files it writes in `<dir>` and its manifest, `manifest.json`, are
described in `curation/src/curation/fetch.py`.

It prints its report. First a line saying where the article comes from: `Full text: <PMCID>
(<license>)` or `Full text: <source> (<license>, <URL>)`, ending with `, supplementary files
missing: <names>` when some are, then `, supplementary files over 100 MB: <names>` when some are;
without the article, `Full text: closed — <why>`, or `Full text: not downloaded — <why>` when it
is free but no copy could be downloaded, then every route tried with its outcome. Then one line
per file that could not be converted, with why, per supplementary file missing, with every place
tried, and per supplementary file over 100 MB, with its size when announced and its URL.
"""

import argparse
from pathlib import Path

from curation.fetch import fetch, report_lines

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument("dir", type=Path)
parser.add_argument("pmid", type=int)
args = parser.parse_args()
print("\n".join(report_lines(fetch(args.dir, args.pmid))))
