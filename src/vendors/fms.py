
# src/vendors/fms.py
# ---------------------------------------------------------------
# FMS (SQL Server) vendor adapter.
#
# FMS is a shared, stressed transactional system. Two rules
# follow from that:
#   1. Always go through call_sproc - never inline ad-hoc SQL.
#      Sprocs are the contract; ad-hoc queries break it and
#      bypass DBA-controlled execution plans.
#   2. Every connection has explicit login + query timeouts so
#      a slow FMS doesn't hang the scheduler indefinitely.
#
# Auth mode is decided by the environment, not by this file - see
# get_fms_connection_string() below. Set FMS_USER/FMS_PASSWORD for
# SQL auth; leave them unset for Windows (Trusted) auth. Nothing in
# this module holds a credential.
#
# "Should this machine run FMS ingestion on a schedule" is a
# separate, machine-specific concern - that belongs in
# machine_config (e.g. fms_ingestion_enabled), NOT here. This
# module only knows how to talk to FMS, not whether it should.
#
# Public sprocs (existing on FMS):
#   sp_GetPositions     daily holdings per account
#   sp_GetPortfolios    portfolio metadata
#   sp_GetTransactions  trade-level data
# ---------------------------------------------------------------

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

import pyodbc

from src.shared.env import optional, required

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------
# Connection topology and auth.
#
# Both live in the environment (.env at the repo root), never in
# this file. Topology moves between machines and environments;
# credentials must never be committed at all.
#
# Required:  FMS_SERVER, FMS_DATABASE
# Optional:  FMS_USER + FMS_PASSWORD
#
# Auth mode follows from whether FMS_USER is set:
#   set   -> SQL auth   (UID/PWD)
#   unset -> Windows    (Trusted_Connection=yes)
#
# The FMS auth model has not been confirmed with the DBA, so both
# are supported and the choice is made by configuration alone -
# switching does not require a code change. See ROTATION.md.
# ---------------------------------------------------------------
DRIVER = "{SQL Server}"

# Timeouts (seconds) - kept conservative because FMS is shared.
LOGIN_TIMEOUT_S = 10
QUERY_TIMEOUT_S = 120


def get_fms_connection_string() -> str:
    """
    Single read-point for the FMS connection string, assembled from
    the environment. Every caller goes through here, so the auth mode
    and the topology can change without touching anything else.

    :return: A pyodbc connection string
    :rtype: str
    :raises MissingSecret: If FMS_SERVER/FMS_DATABASE are unset, or if
                           FMS_USER is set without FMS_PASSWORD
    """
    parts = [
        f"DRIVER={DRIVER};",
        f"SERVER={required('FMS_SERVER')};",
        f"DATABASE={required('FMS_DATABASE')};",
    ]

    user = optional('FMS_USER')
    if user:
        parts.append(f"UID={user};")
        parts.append(f"PWD={required('FMS_PASSWORD')};")
    else:
        parts.append("Trusted_Connection=yes;")

    return "".join(parts)


@contextmanager
def get_fms_connection() -> Iterator[pyodbc.Connection]:
    """
    Context-managed read-only connection to FMS. Always closes,
    even on exception. Login + query timeouts set from constants
    above; FMS is shared, so we never block the scheduler.
    """
    conn_str = get_fms_connection_string()
    logger.debug(f"opening FMS connection (login_timeout={LOGIN_TIMEOUT_S}s)")
    conn = pyodbc.connect(conn_str, timeout=LOGIN_TIMEOUT_S, readonly=True)
    conn.timeout = QUERY_TIMEOUT_S
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            logger.warning("error closing FMS connection", exc_info=True)


def call_sproc(
    sproc_name: str,
    params: tuple[Any, ...] = (),
    *,
    max_retries: int = 2,
    backoff_s: float = 5.0,
) -> list[dict]:
    """
    Execute an FMS stored procedure and return rows as list[dict].

    Retries transient errors (timeouts, deadlocks, dropped conns)
    with linear backoff. Does NOT retry logical errors (bad params,
    permission denied) - those bubble immediately.
    """
    placeholders = ",".join("?" * len(params)) if params else ""
    sql = f"EXEC {sproc_name} {placeholders}".strip()

    attempt = 0
    while True:
        attempt += 1
        try:
            with get_fms_connection() as conn:
                cur = conn.cursor()
                t0 = time.monotonic()
                logger.info(f"calling sproc {sproc_name} (attempt {attempt})")
                cur.execute(sql, params)
                cols = [c[0] for c in cur.description] if cur.description else []
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                elapsed = time.monotonic() - t0
                logger.info(
                    f"sproc {sproc_name}: {len(rows)} rows in {elapsed:.1f}s"
                )
                return rows
        except pyodbc.OperationalError as e:
            if attempt > max_retries:
                logger.error(
                    f"sproc {sproc_name} failed after {attempt} attempts: {e}"
                )
                raise
            wait = backoff_s * attempt
            logger.warning(
                f"sproc {sproc_name} transient failure (attempt {attempt}): {e}; "
                f"retrying in {wait:.1f}s"
            )
            time.sleep(wait)
        except pyodbc.Error:
            logger.exception(f"sproc {sproc_name} non-retryable error")
            raise
