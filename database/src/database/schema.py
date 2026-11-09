"""The structure of the Drakkar database, `database/sql/schema.sql`: `write`, run by
`database/scripts/schema.py`, which describes it."""

import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

HEADER = "-- The structure of Drakkar, written by database/scripts/schema.py: never edit it."


def dump() -> str:
    """The structure of Drakkar (`POSTGRES_DB`), as `pg_dump --schema-only` gives it, its
    statements only, after `HEADER`."""
    load_dotenv()
    text = subprocess.run(
        [
            "pg_dump",
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "-h",
            os.environ["POSTGRES_HOST"],
            "-p",
            os.environ["POSTGRES_PORT"],
            "-U",
            os.environ["POSTGRES_USER"],
            os.environ["POSTGRES_DB"],
        ],
        env={**os.environ, "PGPASSWORD": os.environ.get("POSTGRES_PASSWORD", "")},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # Keep the statements only: drop pg_dump's comments and session settings, and its `\restrict`
    # lines, which carry a random key, so the file only changes with the schema.
    lines = [
        line
        for line in text.splitlines()
        if not line.startswith(("--", "SET ", "SELECT pg_catalog.set_config", "\\"))
    ]
    text = "\n".join(lines)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return f"{HEADER}\n\n{text.strip()}\n"


def write(path: Path) -> str:
    """Writes the structure of Drakkar to the file; says whether it changed."""
    text = dump()
    changed = not path.exists() or path.read_text() != text
    path.write_text(text)
    return f"{path}: {'changed' if changed else 'unchanged'}"
