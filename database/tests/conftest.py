"""A fresh test database per test, copied from a template built once per session.

The template is `sql/schema.sql` (`scripts/schema.py`) and `fixture.sql` (`build_fixture.py`),
loaded into `<POSTGRES_DB>_test_template` on the server of `.env`. Each test gets its own copy,
`<POSTGRES_DB>_test`, so tests can commit.
"""

import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

from database.db import connect

HERE = Path(__file__).parent

# Every connection of the tests, scripts included, goes to the test database, never to Drakkar.
load_dotenv()
TEMPLATE = f"{os.environ['POSTGRES_DB']}_test_template"
os.environ["POSTGRES_DB"] = TEMPLATE.removesuffix("_template")


def _admin(sql: str) -> None:
    """Run a database command on the server, retried while another session holds the database:
    autovacuum analyzes a fresh copy within seconds, and our role cannot terminate its worker."""
    for attempt in range(50):
        try:
            with connect(dbname="postgres") as conn:
                conn.autocommit = True
                conn.execute(sql)  # type: ignore[arg-type]
            return
        except (psycopg.errors.ObjectInUse, psycopg.errors.InsufficientPrivilege):
            if attempt == 49:
                raise
            time.sleep(0.1)


@pytest.fixture(scope="session")
def template() -> Iterator[str]:
    name = TEMPLATE
    _admin(f"DROP DATABASE IF EXISTS {name}")
    _admin(f"CREATE DATABASE {name}")
    for path in (HERE.parent / "sql" / "schema.sql", HERE / "fixture.sql"):
        subprocess.run(
            [
                "psql",
                "-q",
                "-v",
                "ON_ERROR_STOP=1",
                "-h",
                os.environ["POSTGRES_HOST"],
                "-p",
                os.environ["POSTGRES_PORT"],
                "-U",
                os.environ["POSTGRES_USER"],
                "-d",
                name,
                "-f",
                str(path),
            ],
            env={**os.environ, "PGPASSWORD": os.environ.get("POSTGRES_PASSWORD", "")},
            check=True,
            capture_output=True,
        )
    yield name
    _admin(f"DROP DATABASE IF EXISTS {name}")


@pytest.fixture
def dbname(template: str) -> Iterator[str]:
    """A fresh copy of the template (`POSTGRES_DB` points to it)."""
    name = os.environ["POSTGRES_DB"]
    _admin(f"DROP DATABASE IF EXISTS {name}")
    _admin(f"CREATE DATABASE {name} TEMPLATE {template}")
    yield name
    _admin(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


@pytest.fixture
def conn(dbname: str) -> Iterator[psycopg.Connection]:
    with connect(dbname=dbname) as conn:
        yield conn
