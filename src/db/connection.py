# src/db/connection.py
# ---------------------------------------------------------------
# get_connection() contextmanager over psycopg3: opens a PostgreSQL
# connection with dict_row rows, commits on clean exit, rolls back on
# exception, always closes. Project-wide connection access point.

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from contextlib import contextmanager

from src.shared.config_pg import get_db_config

def _get_connection(config: dict = None) -> Connection:
    """
    Open a PostgreSQL connection with sensible defaults:
        - dict_row row factory for dict-like access (replaces sqlite3.Row)
        - Foreign keys are enforced by default in PostgreSQL (no PRAGMA needed)
        - WAL is the default journal mode in PostgreSQL (no PRAGMA needed)

    :param config: Dict with connection params (host, port, dbname, user,
                   password). If None, resolved from the environment.
    :type config: dict
    :return: Connection object to database
    :rtype: psycopg.Connection
    """

    if config is None:
            config = get_db_config()

    conn = psycopg.connect(
            host=config["host"],
            port=config["port"],
            dbname=config["dbname"],
            user=config["user"],
            password=config["password"],
            row_factory=dict_row,
    )
    return conn

@contextmanager
def get_connection(config: dict = None):
    """
    Context manager for safe connection handling.
    Commits on clean exit, rolls back on exception.

    Usage:
        with get_connection() as conn:
            conn.execute(...)
    
    :param config: Dict with connection params
    :type config: dict
    """
    conn = _get_connection(config)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
