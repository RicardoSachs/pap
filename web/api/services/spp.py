# web/api/services/spp.py
# ---------------------------------------------------------------------------
# SPP valor cuota service: everything the tablero reads and nothing that
# writes. Ported from the standalone monitor's read paths (status / windows
# / positions / table) onto the dimensional model.
#
# The monitor stored the book as one wide table; here it lives long in
# fact_prices. read() rebuilds the wide frame (date x '{key}_f{n}[suffix]')
# by pivoting, so the ported window/ranking logic runs unchanged - those
# calculations are share-grid by nature (one common closing-date grid for
# all AFPs, or relative performance would compare different periods).
#
# Metric keys (valor_cuota, cuotas, fondo) are the SBS's own names for the
# published figures and stay as they come; everything else is English.
# ---------------------------------------------------------------------------
from __future__ import annotations

import datetime as dt
import io
import logging

import numpy as np
import pandas as pd

from src.db.connection import get_connection
from src.pipelines.analytics.benchmark import definitions as benchmark_defs
from src.pipelines.prices.sbs.valor_cuota import afps

logger = logging.getLogger(__name__)

SUFFIX = {"valor_cuota": "", "cuotas": "_cuotas", "fondo": "_fondo"}
METRICS = list(SUFFIX)

# What the tablero's selector OFFERS, which is not what is stored. 'cuotas'
# is still scraped, loaded and served - the closing table shows it and the
# API accepts it by name - but as a series to chart it says nothing: units
# outstanding are administrative, not a price, and their return means
# nothing. Dropping it from METRICS would have dropped it from the data:
# that list also decides which columns are read.
PANEL_METRICS = ["valor_cuota", "fondo"]

SHORT_MONTHS = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
                "JUL", "AGO", "SET", "OCT", "NOV", "DIC"]

# Window keys and labels. Column order is CHRONOLOGICAL, oldest on the left
# and the control date on the right, so the tables read in the same
# direction as the line chart and the positions heatmap. Mixed windows are
# ordered by their START date: last year < YTD < M-2 < M-1 < MTD < 5D < the
# daily moves < the level.
LEVEL_KEYS = ["year1", "year", "month2", "month1", "month",
              "t5", "t4", "t3", "t2", "t1", "t"]
RETURN_KEYS = [
    ("a1",    None,          "pct"),
    # The fiscal year starts on 31/10, i.e. BEFORE 1/1 except in November
    # and December, when the fiscal year has started and the calendar year
    # has not. The column does not move those two months: reordering it
    # twice a year would cost more than it clarifies.
    ("fy",    "FY",          "pct"),
    ("ytd",   "YTD",         "pct"),
    ("m2",    None,          "bps"),
    ("m1",    None,          "bps"),
    ("mtd",   "MTD",         "bps"),
    ("d5",    "5D",          "bps"),
    ("d3",    None,          "bps"),
    ("d2",    None,          "bps"),
    ("d1",    None,          "bps"),
    ("d0",    None,          "bps"),
    ("level", "Valor cuota", "level"),
]


def column(afp, fund: int, metric: str = "valor_cuota") -> str:
    """'{key}_f{n}[suffix]' - the monitor's stable column identity."""
    key = afps.key_of(afp)
    if not key:
        raise ValueError(f"Unknown AFP: {afp}")
    return f"{key}_f{int(fund)}{SUFFIX[metric]}"


def house() -> str:
    """The house AFP's display name."""
    return afps.name_of(afps.house_afp())


def _valid_metric(metric) -> str:
    m = str(metric or "valor_cuota").strip()
    return m if m in SUFFIX else "valor_cuota"


def _requested_metrics(metric: str) -> list[str]:
    """'all' -> the three metrics, anything else -> its valid one."""
    return list(METRICS) if metric == "all" else [_valid_metric(metric)]


def _control_date(dates: list, day) -> dt.date | None:
    """Snaps the requested control date to the last close <= it (the
    common rule of windows() and positions()); None when nothing
    precedes it."""
    control = pd.to_datetime(day).date() if day else dates[-1]
    if control in dates:
        return control
    earlier = [d for d in dates if d <= control]
    return earlier[-1] if earlier else None


def _cell(by_date: pd.DataFrame, col: str, day):
    """One cell of the wide book, None-safe (shared lookup of windows()
    and positions())."""
    if day is None or col not in by_date.columns:
        return None
    try:
        v = by_date.at[day, col]
    except KeyError:
        return None
    return None if pd.isna(v) else float(v)


def _last_date():
    """Cheap MAX(date) probe so heavy readers can bound read() relative
    to the book's real end instead of fetching 30 years to use two."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT MAX(fp.date) AS last_date
            FROM fact_prices fp
            JOIN series_registry sr ON sr.series_id = fp.series_id
            JOIN dim_entity e ON e.entity_id = sr.entity_id
            WHERE e.procode LIKE 'SPP\\_%%' AND e.entity_type = 'fund'
              AND sr.source = %s
            """, (afps.SOURCE_SBS_SPP,))
        row = cur.fetchone()
    return row["last_date"] if row else None


# ---- Book reader ----------------------------------------------------------

def read(metrics: list[str] | None = None,
         date_from=None, date_to=None) -> pd.DataFrame:
    """
    Wide DataFrame: one row per date, one column per AFP x fund x metric,
    named '{key}_f{n}[suffix]'. Only the requested metrics are pivoted -
    status() needs all three, a chart request needs one.
    """
    metrics = [m for m in (metrics or METRICS) if m in SUFFIX] or METRICS
    fields = [afps.METRIC_FIELD[m] for m in metrics]

    sql = """
        SELECT e.procode, sr.field, fp.date, fp.price
        FROM fact_prices fp
        JOIN series_registry sr ON sr.series_id = fp.series_id
        JOIN dim_entity e ON e.entity_id = sr.entity_id
        WHERE e.procode LIKE 'SPP\\_%%' AND e.entity_type = 'fund'
          AND sr.source = %s
          AND sr.field = ANY(%s)
    """
    params: list = [afps.SOURCE_SBS_SPP, fields]
    if date_from:
        sql += " AND fp.date >= %s::date"
        params.append(str(date_from))
    if date_to:
        sql += " AND fp.date <= %s::date"
        params.append(str(date_to))

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["date"])

    records = []
    for r in rows:
        parsed = afps.parse_procode(r["procode"])
        if parsed is None:
            continue
        key, fund = parsed
        metric = afps.FIELD_METRIC.get(r["field"])
        if metric is None:
            continue
        records.append({"date": r["date"],
                        "col": f"{key}_f{fund}{SUFFIX[metric]}",
                        "value": r["price"]})
    if not records:
        return pd.DataFrame(columns=["date"])

    df = (pd.DataFrame(records)
          .pivot_table(index="date", columns="col", values="value", aggfunc="last")
          .sort_index().reset_index())
    df.columns.name = None
    return df


# ---- Config ---------------------------------------------------------------

def config() -> dict:
    """The AFP registry the interface consumes - it never names an AFP -
    plus the benchmarks declared in the database."""
    with get_connection() as conn:
        benchmarks = benchmark_defs.benchmarks(conn)
    return {
        "funds": afps.funds(),
        "house": house(),
        "metrics": [{"key": k, "label": afps.METRIC_LABEL[k]} for k in PANEL_METRICS],
        "afps": [{"key": a["key"],
                  "name": a["name"],
                  "color": a.get("color", "#1A1A1A"),
                  "color_solid": a.get("color_solid", a.get("color", "#1A1A1A")),
                  "house": bool(a.get("house")),
                  "funds": afps.funds_of(a["key"])}
                 for a in afps.afps()],
        # The composite indices are no longer one slot per fund type: any
        # dim_portfolio row of type benchmark, by procode, with the name
        # business knows it by.
        "benchmarks": [{"portfolio_id": b["portfolio_id"], "procode": b["procode"],
                        "display_name": b["display_name"] or b["procode"]}
                       for b in benchmarks],
    }


# ---- Status ---------------------------------------------------------------

def gaps(dates, minimum: int = 3) -> list:
    """
    Consecutive business days without data inside the loaded range. The
    source has no holiday calendar, so Peruvian holidays show as empty
    business days; typical blocks span 2, so only runs of `minimum`+ are
    real missing information.
    """
    dates = list(dates)
    if len(dates) < 2:
        return []
    loaded = {pd.to_datetime(d).date() for d in dates}
    missing = sorted(set(pd.bdate_range(min(loaded), max(loaded)).date) - loaded)
    if not missing:
        return []
    runs, current = [], [missing[0]]
    for previous, following in zip(missing, missing[1:]):
        if int(np.busday_count(previous + dt.timedelta(days=1), following)) == 0:
            current.append(following)
        else:
            runs.append(current)
            current = [following]
    runs.append(current)
    return [{"from": str(r[0]), "to": str(r[-1]), "days": len(r)}
            for r in runs if len(r) >= minimum]


def _metric_coverage(df: pd.DataFrame, metric: str) -> dict:
    cols = [c for c in _columns_of(metric) if c in df.columns]
    if not cols or df.empty:
        return {"metric": metric, "dates": 0, "from": None, "to": None}
    with_data = df[df[cols].notna().any(axis=1)]
    if with_data.empty:
        return {"metric": metric, "dates": 0, "from": None, "to": None}
    return {"metric": metric, "dates": int(len(with_data)),
            "from": str(with_data["date"].min()),
            "to": str(with_data["date"].max())}


def _columns_of(metric: str) -> list[str]:
    return [column(a, f, metric)
            for f in afps.funds() for a in afps.names() if afps.operates(a, f)]


def status() -> dict:
    """Summary for the tablero: coverage, latest values, gaps, variations."""
    df = read()
    base = {"table": "fact_prices", "rows": len(df), "from": None, "to": None,
            "gaps": [], "series": [], "complete": 0, "partial": 0,
            "metrics": [_metric_coverage(df, m) for m in METRICS]}
    if df.empty:
        return base

    base.update({"from": str(df["date"].min()), "to": str(df["date"].max()),
                 "gaps": gaps(df["date"])})

    # A "complete" date has all valor cuota series published; usable
    # coverage runs to the last of those - a half-published date is not
    # coverage.
    present = [c for c in _columns_of("valor_cuota") if c in df.columns]
    complete = df[present].notna().all(axis=1) if present else df["date"].isna()
    base["complete"] = int(complete.sum())
    base["partial"] = int((~complete).sum())
    complete_dates = df.loc[complete, "date"]
    base["from_complete"] = str(complete_dates.min()) if len(complete_dates) else None
    base["to_complete"] = str(complete_dates.max()) if len(complete_dates) else None
    base["partial_after"] = (
        int((df["date"] > complete_dates.max()).sum()) if len(complete_dates) else 0)

    # Staleness KPI, owned here next to the coverage semantics it depends
    # on (the dashboard only renders tone): business days elapsed since
    # the last COMPLETE close, and the data-quality classification.
    end = complete_dates.max() if len(complete_dates) else df["date"].max()
    today = dt.date.today()
    lag = int(np.busday_count(end + dt.timedelta(days=1),
                              today + dt.timedelta(days=1))) if end < today else 0
    open_gaps = len(base["gaps"])
    if lag > 3 or open_gaps > 1:
        integrity = "exceeded"
    elif open_gaps == 1 or lag > 1:
        integrity = "watch"
    else:
        integrity = "ok"
    base["lag_business_days"] = max(lag, 0)
    base["integrity"] = integrity

    def last_and_change(col):
        if col not in df.columns:
            return None, None, None
        s = df[["date", col]].dropna(subset=[col])
        if s.empty:
            return None, None, None
        last = float(s[col].iloc[-1])
        previous = float(s[col].iloc[-2]) if len(s) > 1 else None
        change = None if not previous else round((last / previous - 1) * 10000, 1)
        return last, change, str(s["date"].iloc[-1])

    for f in afps.funds():
        for a in afps.names():
            if not afps.operates(a, f):
                continue
            col = column(a, f)
            if col not in df.columns:
                continue
            s = df[["date", col]].dropna(subset=[col])
            if s.empty:
                continue
            vc, vc_change, vc_date = last_and_change(col)
            units, units_change, units_date = last_and_change(column(a, f, "cuotas"))
            value, value_change, value_date = last_and_change(column(a, f, "fondo"))
            base["series"].append({
                "afp": a, "fund": f, "column": col,
                "date": vc_date, "value": vc, "var_bps": vc_change,
                "cuotas": units, "cuotas_var_bps": units_change, "cuotas_date": units_date,
                "fondo_soles": value, "fondo_var_bps": value_change, "fondo_date": value_date,
                "points": int(len(s)),
                "start": str(s["date"].iloc[0]),
            })
    return base


# ---- Series (chart) -------------------------------------------------------

def series(fund: int, requested_afps: list[str] | None, metric: str,
           date_from=None, date_to=None) -> dict:
    metric = _valid_metric(metric)
    fund = int(fund) if int(fund) in afps.funds() else afps.funds()[0]
    names = afps.names()
    requested = [a for a in (requested_afps or []) if a in names] or names

    df = read([metric], date_from, date_to)
    if df.empty:
        return {"fund": fund, "metric": metric, "series": []}

    out = []
    for afp in requested:
        col = column(afp, fund, metric)
        if col not in df.columns:
            out.append({"afp": afp, "points": []})
            continue
        s = df[["date", col]].dropna(subset=[col])
        out.append({
            "afp": afp,
            "points": [[str(d), float(v)] for d, v in zip(s["date"], s[col])],
        })
    return {"fund": fund, "metric": metric, "series": out}


# ---- Performance windows --------------------------------------------------

def _dm(d):
    return d.strftime("%d/%m") if d else "—"


def _dmy(d):
    return d.strftime("%d/%m/%y") if d else "—"


def _short_month(d):
    return f"{SHORT_MONTHS[d.month - 1]} {d.strftime('%y')}" if d else "—"


def _first_of_month(d: dt.date, back: int = 0) -> dt.date:
    y, m = d.year, d.month - back
    while m <= 0:
        m += 12
        y -= 1
    return dt.date(y, m, 1)


def fiscal_year_start(d: dt.date) -> dt.date:
    """
    Day the fiscal year containing `d` starts. The year runs 31/10 to
    31/10.

    The boundary date belongs to the year that ENDS on it: standing on
    31/10 the operator is reading the twelve months just closed, not a
    year that is one day old. So the new year starts on 1/11, and the
    close of 31/10 is its base - which is what "since 31/10" means.
    """
    year = d.year if d > dt.date(d.year, 10, 31) else d.year - 1
    return dt.date(year, 11, 1)


def _last_before(dates: list, limit: dt.date):
    earlier = [d for d in dates if d < limit]
    return earlier[-1] if earlier else None


def reference_dates(dates: list, control: dt.date) -> dict:
    """
    Base dates of every window on the COMMON closing grid - one grid for
    all series, or relative returns would compare different periods.
    Month/year bases are the LAST CLOSE OF THE PRIOR PERIOD (the desk
    standard), so MTD includes the first business day.
    """
    earlier = [d for d in dates if d < control]
    ref = {"t": control}
    for i in range(1, 6):
        ref[f"t{i}"] = earlier[-i] if len(earlier) >= i else None
    ref["month"] = _last_before(dates, _first_of_month(control, 0))
    ref["month1"] = _last_before(dates, _first_of_month(control, 1))
    ref["month2"] = _last_before(dates, _first_of_month(control, 2))
    ref["year"] = _last_before(dates, dt.date(control.year, 1, 1))
    ref["year1"] = _last_before(dates, dt.date(control.year - 1, 1, 1))
    # The fiscal year: same rule as the month and the year - the base is
    # the last close of the previous period, i.e. 31/10 (or October's last
    # trading day when the 31st fell on a weekend or holiday).
    ref["fy"] = _last_before(dates, fiscal_year_start(control))
    return ref


def _change(current, base):
    if current is None or base is None or base == 0:
        return None
    return current / base - 1.0


def windows(day=None, metric: str = "valor_cuota") -> dict:
    """
    Levels, absolute returns and relative returns (house minus each
    competitor) per AFP and fund, on the common closing grid.
    """
    metric = _valid_metric(metric)
    empty = {"control": None, "dates": {}, "metric": metric, "levels": [],
             "absolute": [], "relative": [], "level_columns": [], "return_columns": []}
    # Every window base (t-5, month starts, 31/10 of the fiscal year, Jan 1
    # of the prior year) lives within two calendar years of the control
    # date: bound the read there instead of pulling the book since 1993 on
    # every request.
    last = _last_date()
    if last is None:
        return empty
    anchor = min(pd.to_datetime(day).date(), last) if day else last
    df = read([metric], date_from=dt.date(anchor.year - 2, 1, 1))
    if df.empty:
        return empty

    dates = sorted(df["date"].tolist())
    control = _control_date(dates, day)
    if control is None:
        return empty

    ref = reference_dates(dates, control)
    by_date = df.set_index("date")

    def cell(col, d):
        return _cell(by_date, col, d)

    names = afps.names()
    levels, absolute, returns = [], [], {}

    for f in afps.funds():
        for a in names:
            if not afps.operates(a, f):
                continue
            col = column(a, f, metric)
            v = {k: cell(col, ref.get(k)) for k in ref}

            levels.append({"afp": a, "fund": f,
                           "values": {k: v.get(k) for k in LEVEL_KEYS}})

            r = {
                "level": v["t"],
                "d0":  _change(v["t"],  v["t1"]),
                "d1":  _change(v["t1"], v["t2"]),
                "d2":  _change(v["t2"], v["t3"]),
                "d3":  _change(v["t3"], v["t4"]),
                "d5":  _change(v["t"],  v["t5"]),
                "mtd": _change(v["t"],  v["month"]),
                "m1":  _change(v["month"],  v["month1"]),
                "m2":  _change(v["month1"], v["month2"]),
                "fy":  _change(v["t"],    v["fy"]),
                "ytd": _change(v["t"],    v["year"]),
                "a1":  _change(v["year"], v["year1"]),
            }
            returns[(a, f)] = r
            absolute.append({"afp": a, "fund": f, "values": r})

    # Relative: the house appears too, but with its ABSOLUTE return - the
    # baseline the differences are read against.
    keys = [k for k, _, u in RETURN_KEYS if u != "level"]
    house_afp = house()
    relative = []
    for f in afps.funds():
        if (house_afp, f) not in returns:
            continue
        base = returns[(house_afp, f)]
        relative.append({"afp": house_afp, "fund": f, "absolute": True,
                         "values": {k: base.get(k) for k in keys}})
        for a in names:
            if a == house_afp or (a, f) not in returns:
                continue
            other = returns[(a, f)]
            diff = {k: (None if (base.get(k) is None or other.get(k) is None)
                        else base[k] - other[k]) for k in keys}
            relative.append({"afp": a, "fund": f, "absolute": False, "values": diff})

    level_columns = [[k, (_dmy(ref[k]) if k in ("year", "year1") else _dm(ref[k]))]
                     for k in LEVEL_KEYS]
    return_labels = {
        "d0": _dm(ref["t"]), "d1": _dm(ref["t1"]),
        "d2": _dm(ref["t2"]), "d3": _dm(ref["t3"]),
        "m1": _short_month(ref["month"]),
        "m2": _short_month(ref["month1"]),
        "a1": ref["year"].strftime("%Y") if ref["year"] else "—",
    }
    return_columns = [[k, (fixed or return_labels.get(k, k)), u]
                      for k, fixed, u in RETURN_KEYS]

    return {"control": str(control),
            "dates": {k: (str(x) if x else None) for k, x in ref.items()},
            "metric": metric,
            "levels": levels, "absolute": absolute, "relative": relative,
            "level_columns": level_columns, "return_columns": return_columns}


# ---- Monthly positions ----------------------------------------------------

def positions(day=None, months: int = 24, metric: str = "valor_cuota") -> dict:
    """
    Monthly performance rank per AFP, grouped by FUND TYPE - ranking only
    makes sense between portfolios of the same risk profile. Each closed
    month returns close-vs-prior-close; the last period is the MTD.
    """
    metric = _valid_metric(metric)
    empty = {"control": None, "metric": metric, "total_afp": 0, "periods": [], "rows": []}
    # `months` closed months plus the extra base month and MTD: bound the
    # read to that window instead of the whole book.
    last = _last_date()
    if last is None:
        return empty
    anchor = min(pd.to_datetime(day).date(), last) if day else last
    start = _first_of_month(anchor, int(months) + 2)
    df = read([metric], date_from=start)
    if df.empty:
        return empty

    dates = sorted(df["date"].tolist())
    control = _control_date(dates, day)
    if control is None:
        return empty

    by_month: dict[tuple, dt.date] = {}
    for d in dates:
        if d > control:
            break
        by_month[(d.year, d.month)] = d    # last close of each month wins
    closed = sorted(k for k in by_month if k < (control.year, control.month))
    if len(closed) < 2:
        return empty

    use = closed[-(int(months) + 1):]   # one extra as the first base
    periods = []
    for i in range(1, len(use)):
        year, month = use[i]
        periods.append({
            "key": f"{year:04d}-{month:02d}",
            "label": f"{SHORT_MONTHS[month - 1]} {str(year)[2:]}",
            "start": by_month[use[i - 1]], "end": by_month[use[i]],
        })
    periods.append({"key": "MTD", "label": "MTD",
                    "start": by_month[closed[-1]], "end": control})

    by_date = df.set_index("date")

    def cell(col, d):
        return _cell(by_date, col, d)

    names = afps.names()
    rows = []
    for f in afps.funds():
        competing = [a for a in names if afps.operates(a, f)]
        returns = {a: {} for a in competing}
        for p in periods:
            for a in competing:
                col = column(a, f, metric)
                returns[a][p["key"]] = _change(cell(col, p["end"]), cell(col, p["start"]))
        ranks = {a: {} for a in competing}
        for p in periods:
            k = p["key"]
            alive = [(a, returns[a][k]) for a in competing if returns[a][k] is not None]
            for rank, (a, _) in enumerate(sorted(alive, key=lambda x: -x[1]), start=1):
                ranks[a][k] = rank
        for a in competing:
            rows.append({"fund": f, "afp": a, "ranks": ranks[a], "returns": returns[a]})

    return {"control": str(control), "metric": metric,
            "total_afp": max((len([a for a in names if afps.operates(a, f)])
                              for f in afps.funds()), default=len(names)),
            "periods": [{"key": p["key"], "label": p["label"],
                         "from": str(p["start"]), "to": str(p["end"])}
                        for p in periods],
            "rows": rows}


# ---- Book (table + export) ------------------------------------------------

def requested_columns(metric: str, fund_arg: str) -> list[dict]:
    """
    Screen selection -> concrete columns, so the CSV downloads exactly
    what is on screen. Only combinations that exist: an AFP that does
    not operate a fund must not contribute a dash column.
    """
    metrics = _requested_metrics(metric)

    if fund_arg == "all":
        selected_funds = afps.funds()
    else:
        try:
            f = int(fund_arg)
            selected_funds = [f] if f in afps.funds() else afps.funds()
        except (TypeError, ValueError):
            selected_funds = afps.funds()

    return [{"col": column(a, f, m), "afp": a, "fund": f, "metric": m}
            for f in selected_funds for a in afps.names() if afps.operates(a, f)
            for m in metrics]


def _recent_cut(metrics: list[str], n: int, date_to=None):
    """
    First date of the last `n` distinct dates carrying any of the given
    metrics - resolved in SQL so a 60-row view does not fetch and pivot
    the book since 1993 to keep 60 dates.
    """
    fields = [afps.METRIC_FIELD[m] for m in metrics]
    sql = """
        SELECT DISTINCT fp.date
        FROM fact_prices fp
        JOIN series_registry sr ON sr.series_id = fp.series_id
        JOIN dim_entity e ON e.entity_id = sr.entity_id
        WHERE e.procode LIKE 'SPP\\_%%' AND e.entity_type = 'fund'
          AND sr.source = %s AND sr.field = ANY(%s)
    """
    params: list = [afps.SOURCE_SBS_SPP, fields]
    if date_to:
        sql += " AND fp.date <= %s::date"
        params.append(str(date_to))
    sql += " ORDER BY fp.date DESC LIMIT %s"
    params.append(int(n))
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
    return rows[-1]["date"] if rows else None


def table(limit: int | None, metric: str, fund_arg: str) -> dict:
    """The book, most recent first. limit=None is the whole book."""
    selected = requested_columns(metric, fund_arg)
    metrics = _requested_metrics(metric)
    date_from = _recent_cut(metrics, limit) if limit else None
    df = read(metrics, date_from=date_from)
    if df.empty:
        return {"columns": selected, "metric": metric, "fund": fund_arg, "rows": []}

    cut = (df if limit is None else df.tail(int(limit))).iloc[::-1]
    col_names = [c["col"] for c in selected]
    rows = []
    for _, row in cut.iterrows():
        rows.append({"date": str(row["date"]),
                     "values": [None if (c not in df.columns or pd.isna(row[c]))
                                else float(row[c]) for c in col_names]})
    return {"columns": selected, "metric": metric, "fund": fund_arg, "rows": rows}


def benchmark_table(procode: str, limit: int | None) -> dict | None:
    """
    One benchmark's levels over the SAME date grid as the book.

    The question this table answers is "which days is the index
    missing", so the rows are the days WITH valor cuota - not the days
    the index has. Listing only the latter would make a day without a
    level simply disappear, which is exactly what one needs to see.
    Returns None for an unknown benchmark.
    """
    with get_connection() as conn:
        bench = benchmark_defs.benchmark_by_procode(conn, procode)
        if bench is None or bench["series_id"] is None:
            return None
        date_from = _recent_cut(["valor_cuota"], limit) if limit else None
        book = read(["valor_cuota"], date_from=date_from)
        if book.empty:
            return {"procode": procode, "display_name": bench["display_name"],
                    "columns": [], "rows": [], "missing": 0, "dates": 0}
        grid = (book if limit is None else book.tail(int(limit)))["date"]
        cur = conn.cursor()
        cur.execute(
            "SELECT date, price FROM fact_prices WHERE series_id = %s "
            "AND date BETWEEN %s AND %s",
            (bench["series_id"], grid.min(), grid.max()))
        levels = {r["date"]: float(r["price"]) for r in cur.fetchall()}

    rows, missing = [], 0
    for day in grid.iloc[::-1]:
        level = levels.get(day)
        if level is None:
            missing += 1
        rows.append({"date": str(day), "values": [level]})
    return {"procode": procode, "display_name": bench["display_name"] or procode,
            "columns": [{"col": procode, "label": bench["display_name"] or procode}],
            "rows": rows, "missing": missing, "dates": len(rows)}


def export_csv(metric: str, fund_arg: str, limit: int | None,
               date_from=None, date_to=None) -> bytes:
    """The same cut as table(), as CSV bytes built in memory."""
    selected = [c["col"] for c in requested_columns(metric, fund_arg)]
    metrics = _requested_metrics(metric)
    if limit:
        cut = _recent_cut(metrics, limit, date_to=date_to)
        if cut is not None:
            date_from = max(pd.to_datetime(date_from).date(), cut) if date_from else cut
    df = read(metrics, date_from, date_to)
    present = [c for c in selected if c in df.columns]
    df = df[["date"] + present] if not df.empty else df
    if limit and not df.empty:
        df = df.tail(int(limit))
    if not df.empty:
        df = df.sort_values("date", ascending=False)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8-sig")
