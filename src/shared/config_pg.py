
# src/shared/config_pg.py
# ---------------------------------------------------------------
# PostgreSQL connection config, read from the environment.
#
# This is the single choke point for DB credentials: every caller in
# the project - the pipelines, the scripts, and the FastAPI backend in
# web/api - reaches Postgres through src.db.connection.get_connection(),
# which reads from here.
#
# Resolution is lazy and cached. Doing it at import time would raise
# on a missing secret before anything has actually asked for a
# connection, which would break `uvicorn web.api.main:app` at startup
# and every script that merely imports the package. Deferring to first
# use means the error surfaces where it is actionable.
# ---------------------------------------------------------------

from functools import lru_cache

from src.shared.env import optional, required


@lru_cache(maxsize=1)
def get_db_config() -> dict:
    '''
    Returns the PostgreSQL connection parameters from the environment.

    Every value except the port is required - there is deliberately no
    fallback for host, dbname, user or password. A missing one raises
    MissingSecret naming the key, rather than silently connecting
    somewhere unintended.

    :return: Dict with host, port, dbname, user, password
    :rtype: dict
    :raises MissingSecret: If any required key is unset
    '''
    return {
        'host':     required('PG_HOST'),
        'port':     optional('PG_PORT', '5432'),
        'dbname':   required('PG_DBNAME'),
        'user':     required('PG_USER'),
        'password': required('PG_PASSWORD'),
    }
