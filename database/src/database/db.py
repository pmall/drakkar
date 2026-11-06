"""Database connection, configured from the project's `.env` file."""

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import psycopg
from dotenv import load_dotenv


def connect(*, readonly: bool = False, dbname: str | None = None) -> psycopg.Connection:
    """A connection to the Drakkar database (`POSTGRES_DB`), or to `dbname` on the same server."""
    load_dotenv()
    options = "-c default_transaction_read_only=on" if readonly else ""
    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=dbname or os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ.get("POSTGRES_PASSWORD"),
        options=options,
    )


def require_idle(conn: psycopg.Connection) -> None:
    """Refuses a connection with a transaction in progress: a write runs in a transaction of its
    own, which it ends itself."""
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise RuntimeError("the connection has a transaction in progress")


@contextmanager
def reading(timeout: str = "30s") -> Generator[Any]:
    """A cursor on a read-only connection to Drakkar, each statement stopped after `timeout`."""
    with connect(readonly=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('statement_timeout', %s, false)", (timeout,))
        yield cur
