"""Write the structure of the Drakkar database (tables, constraints, indexes) from the database
itself, with `pg_dump`.

    uv run ./database/scripts/schema.py

Writes `database/sql/schema.sql`, its statements only, never edited by hand: run it after every
change of structure. The tests build their database from it and from their fixture
(`database/tests/build_fixture.py`). Prints the file and whether it changed.
"""

import argparse
from pathlib import Path

from database.schema import write

SCHEMA = Path(__file__).parent.parent / "sql" / "schema.sql"

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.parse_args()
print(write(SCHEMA))
