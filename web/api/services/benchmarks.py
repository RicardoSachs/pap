# web/api/services/benchmarks.py
# ---------------------------------------------------------------------------
# Benchmarks service: what the tablero reads and writes about the
# composite indices, over src/pipelines/analytics/benchmark. The analytics
# module owns the rules (append-only versions, the chaining arithmetic,
# the three outputs); this module shapes its answers for the screen and
# resolves the catalog of series a basket can draw from.
# ---------------------------------------------------------------------------
from __future__ import annotations

import io
import logging

import pandas as pd

from src.db.connection import get_connection
from src.pipelines.analytics.benchmark import definitions
from src.pipelines.analytics.benchmark.materialize import SOURCE_MODEL, materialize
from web.api.services.spp import read as read_book, recent_cut

logger = logging.getLogger(__name__)


def _summary(conn, bench: dict) -> dict:
    """One benchmark with its coverage: versions, stored levels, last level."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM dim_benchmark_version WHERE portfolio_id = %s",
                (bench["portfolio_id"],))
    versions = cur.fetchone()["n"]
    points, first, last, last_level = 0, None, None, None
    if bench["series_id"] is not None:
        cur.execute(
            "SELECT COUNT(*) AS n, MIN(date) AS first, MAX(date) AS last "
            "FROM fact_prices WHERE series_id = %s", (bench["series_id"],))
        row = cur.fetchone()
        points, first, last = row["n"], row["first"], row["last"]
        if last is not None:
            cur.execute("SELECT price FROM fact_prices WHERE series_id = %s AND date = %s",
                        (bench["series_id"], last))
            last_level = float(cur.fetchone()["price"])
    return {
        "portfolio_id": bench["portfolio_id"], "procode": bench["procode"],
        "display_name": bench["display_name"] or bench["procode"],
        "base_currency": bench["base_currency"], "status": bench["status"],
        "entity_id": bench["entity_id"], "series_id": bench["series_id"],
        "versions": int(versions), "points": int(points),
        "from": str(first) if first else None, "to": str(last) if last else None,
        "last_level": last_level,
    }


def list_benchmarks() -> list[dict]:
    with get_connection() as conn:
        return [_summary(conn, b) for b in definitions.benchmarks(conn, status=None)]


def get(procode: str) -> dict | None:
    with get_connection() as conn:
        bench = definitions.benchmark_by_procode(conn, procode)
        if bench is None or bench["portfolio_type"] != definitions.PORTFOLIO_TYPE:
            return None
        return _summary(conn, bench)


def create(procode: str, display_name: str, base_currency: str = "PEN") -> dict:
    """Creates a benchmark or renames it (the procode is the identity)."""
    with get_connection() as conn:
        bench = definitions.ensure_benchmark(conn, procode, display_name, base_currency)
        return _summary(conn, bench)


def _portfolio_id(conn, procode: str) -> int:
    bench = definitions.benchmark_by_procode(conn, procode)
    if bench is None or bench["portfolio_type"] != definitions.PORTFOLIO_TYPE:
        raise LookupError(procode)
    return bench["portfolio_id"]


def versions(procode: str) -> list[dict]:
    """Every version with its basket, oldest first."""
    with get_connection() as conn:
        pid = _portfolio_id(conn, procode)
        out = []
        for v in definitions.versions(conn, pid):
            basket = definitions.constituents(conn, v["version_id"])
            out.append({
                **{k: v[k] for k in ("version_id", "effective_from", "method",
                                     "rebalance_frequency", "change_type", "reason",
                                     "support_doc", "recorded_by", "supersedes_version_id")},
                "created_at": v["created_at"].isoformat(timespec="seconds"),
                "constituents": [{"series_id": c["series_id"], "label": c["label"],
                                  "weight": float(c["weight"]),
                                  "fx_series_id": c["fx_series_id"],
                                  "procode": c["procode"], "field": c["field"],
                                  "source": c["source"]} for c in basket],
            })
        return out


def changelog(procode: str) -> list[dict]:
    with get_connection() as conn:
        pid = _portfolio_id(conn, procode)
        rows = definitions.changelog(conn, pid)
    return [{**r, "created_at": r["created_at"].isoformat(timespec="seconds"),
             "weight_before": None if r["weight_before"] is None else float(r["weight_before"]),
             "weight_after": None if r["weight_after"] is None else float(r["weight_after"]),
             "weight_delta": float(r["weight_delta"])} for r in rows]


def add_version(procode: str, payload: dict) -> int:
    """Appends one version. ValueError from the writer names the problem."""
    with get_connection() as conn:
        pid = _portfolio_id(conn, procode)
        return definitions.add_version(
            conn, pid,
            effective_from=payload["effective_from"],
            method=payload.get("method") or "buy_and_hold",
            change_type=payload["change_type"],
            reason=payload.get("reason"),
            constituents=payload.get("constituents") or [],
            rebalance_frequency=payload.get("rebalance_frequency"),
            support_doc=payload.get("support_doc"),
            recorded_by=payload.get("recorded_by"),
            supersedes_version_id=payload.get("supersedes_version_id"),
        )


def rebuild(procode: str) -> dict:
    """Materializes one benchmark in its own transaction (runs in the task)."""
    with get_connection() as conn:
        pid = _portfolio_id(conn, procode)
        summary = materialize(conn, pid)
    summary["from"] = str(summary["from"])
    summary["to"] = str(summary["to"])
    return summary


def series_catalog(q: str = "", limit: int = 50) -> list[dict]:
    """
    Pickable series for the basket editor: the pipeline spine, without
    the model series themselves - an index built from another index is a
    loop waiting to happen.
    """
    pattern = f"%{q.strip()}%" if q.strip() else "%"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT sr.series_id, e.procode, e.name, sr.field, sr.source
            FROM series_registry sr
            JOIN dim_entity e ON e.entity_id = sr.entity_id
            WHERE sr.source <> %s AND sr.domain = 'prices'
              AND (e.procode ILIKE %s OR COALESCE(e.name, '') ILIKE %s)
            ORDER BY e.procode, sr.field, sr.source
            LIMIT %s
            """, (SOURCE_MODEL, pattern, pattern, int(limit)))
        rows = cur.fetchall()
    return [{"series_id": r["series_id"], "procode": r["procode"], "name": r["name"],
             "field": r["field"], "source": r["source"],
             "label": r["procode"],
             "detail": f"{r['field']} · {r['source']}" + (f" · {r['name']}" if r["name"] else "")}
            for r in rows]


def levels(procode: str, date_from=None, date_to=None) -> pd.DataFrame:
    """The stored level series as a DataFrame (date, level), ascending."""
    with get_connection() as conn:
        bench = definitions.benchmark_by_procode(conn, procode)
        if bench is None or bench["series_id"] is None:
            return pd.DataFrame(columns=["date", "level"])
        sql = "SELECT date, price AS level FROM fact_prices WHERE series_id = %s"
        params: list = [bench["series_id"]]
        if date_from:
            sql += " AND date >= %s::date"
            params.append(str(date_from))
        if date_to:
            sql += " AND date <= %s::date"
            params.append(str(date_to))
        cur = conn.cursor()
        cur.execute(sql + " ORDER BY date", params)
        rows = cur.fetchall()
    return pd.DataFrame([{"date": r["date"], "level": float(r["level"])} for r in rows],
                        columns=["date", "level"])


def export_xlsx(procode: str, date_from=None, date_to=None) -> bytes:
    """The level series as an in-memory Excel, most recent first."""
    df = levels(procode, date_from, date_to)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.sort_values("date", ascending=False).to_excel(
            writer, sheet_name=procode[:31], index=False)
    return buf.getvalue()


def levels_points(procode: str, date_from=None, date_to=None) -> dict | None:
    """The level series as [date, level] points, for the chart; None when
    the benchmark does not exist."""
    with get_connection() as conn:
        bench = definitions.benchmark_by_procode(conn, procode)
    if bench is None or bench["portfolio_type"] != definitions.PORTFOLIO_TYPE:
        return None
    df = levels(procode, date_from, date_to)
    return {"procode": procode, "display_name": bench["display_name"] or procode,
            "points": [[str(d), float(v)] for d, v in zip(df["date"], df["level"])]}


def benchmark_table(procode: str, limit: int | None) -> dict | None:
    """
    One benchmark's levels over the SAME date grid as the valor cuota book.

    The question this table answers is "which days is the index
    missing", so the rows are the days WITH valor cuota - not the days
    the index has. Listing only the latter would make a day without a
    level simply disappear, which is exactly what one needs to see.
    Returns None for an unknown benchmark.
    """
    with get_connection() as conn:
        bench = definitions.benchmark_by_procode(conn, procode)
        if bench is None or bench["series_id"] is None:
            return None
        date_from = recent_cut(["valor_cuota"], limit) if limit else None
        book = read_book(["valor_cuota"], date_from=date_from)
        if book.empty:
            return {"procode": procode, "display_name": bench["display_name"] or procode,
                    "columns": [], "rows": [], "missing": 0, "dates": 0}
        grid = (book if limit is None else book.tail(int(limit)))["date"]
        cur = conn.cursor()
        cur.execute(
            "SELECT date, price FROM fact_prices WHERE series_id = %s "
            "AND date BETWEEN %s AND %s",
            (bench["series_id"], grid.min(), grid.max()))
        stored = {r["date"]: float(r["price"]) for r in cur.fetchall()}

    rows, missing = [], 0
    for day in grid.iloc[::-1]:
        level = stored.get(day)
        if level is None:
            missing += 1
        rows.append({"date": str(day), "values": [level]})
    return {"procode": procode, "display_name": bench["display_name"] or procode,
            "columns": [{"col": procode, "label": bench["display_name"] or procode}],
            "rows": rows, "missing": missing, "dates": len(rows)}
