# src/pipelines/prices/sbs/valor_cuota/afps.py
# ---------------------------------------------------------------
# AFP registry for the SPP valor cuota feed: the bridge between the
# business identities (AFP clave + fund type + metric) and the
# dimensional model (dim_entity procode + series_registry field).
#
# Everything regulation can change lives in config/afps.yaml: a new
# AFP, a renamed one, or an AFP that only operates some fund types.
# This module never names a specific AFP.
#
# The design distinction that everything rests on is CLAVE vs NOMBRE:
#   - clave names the entity procode and NEVER changes;
#   - nombre is display-only and can change any time.
# A corporate rename therefore touches zero historical rows.
#
# Series mapping (one entity per AFP x fund, one series per metric):
#   procode  SPP_{CLAVE}_F{fondo}          entity_type 'fund'
#   fields   PX_LAST (valor cuota), CUOTAS, FONDO_SOLES
#   source   'sbs'
# Benchmark (one per fund type, common to all AFPs):
#   procode  SPP_BENCH_F{fondo}            entity_type 'index'
#   field    PX_LAST                       source 'benchmark'
# PX_LAST for the NAV is deliberate: the existing Price Viewer
# charts PX_LAST across sources, so the funds show up there for free.
# ---------------------------------------------------------------

import logging
import unicodedata
from datetime import date
from functools import lru_cache

import yaml

from src.shared.paths import CONFIG_DIR

logger = logging.getLogger(__name__)

AFPS_CONFIG = CONFIG_DIR / "afps.yaml"

SOURCE_SBS = "sbs"
SOURCE_BENCH = "benchmark"

# metric name (business, as the SBS publishes them) -> series_registry field
METRICA_FIELD = {
    "valor_cuota": "PX_LAST",
    "cuotas": "CUOTAS",
    "fondo": "FONDO_SOLES",
}
FIELD_METRICA = {v: k for k, v in METRICA_FIELD.items()}

ETIQUETA_METRICA = {
    "valor_cuota": "Valor cuota",
    "cuotas": "Cuotas",
    "fondo": "Fondo (S/)",
}

# The SBS historical series starts on 1993-08-02; cuotas and fondo
# only exist from the first daily-page extraction onward, but the
# registry start date is informational, not a hard floor.
DEFAULT_START = date(1993, 8, 2)


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t)
                   if unicodedata.category(c) != "Mn")


def _norm(t) -> str:
    """Normalized AFP name for comparison: no accents, upper, single spaces."""
    return " ".join(_sin_tildes(str(t or "")).upper().split())


@lru_cache(maxsize=1)
def registro() -> dict:
    """Loads and caches config/afps.yaml. Fails loud if absent or empty."""
    with open(AFPS_CONFIG, encoding="utf-8") as f:
        datos = yaml.safe_load(f)
    if not isinstance(datos, dict) or not datos.get("afps"):
        raise ValueError(f"Invalid AFP registry at {AFPS_CONFIG}: 'afps' list required.")
    return datos


def fondos() -> list[int]:
    return [int(f) for f in registro().get("fondos", [0, 1, 2, 3])]


def fondos_benchmark() -> list[int]:
    declared = registro().get("fondos_benchmark", [1, 2, 3])
    return [int(f) for f in declared if int(f) in fondos()]


def afps() -> list[dict]:
    return registro()["afps"]


def claves() -> list[str]:
    return [a["clave"] for a in afps()]


def nombres() -> list[str]:
    return [a["nombre"] for a in afps()]


@lru_cache(maxsize=1)
def _alias_map() -> dict:
    # Any way of naming an AFP -> its clave. Includes clave, current name
    # and all historical aliases, so a rename never breaks recognition of
    # older publications.
    alias = {}
    for a in afps():
        for t in [a["clave"], a["nombre"]] + list(a.get("alias", [])):
            alias[_norm(t)] = a["clave"]
    return alias


def clave_de(afp) -> str | None:
    """Stable clave from a clave, display name, or any registered alias."""
    return _alias_map().get(_norm(afp))


def def_de(afp) -> dict | None:
    c = clave_de(afp)
    return next((a for a in afps() if a["clave"] == c), None) if c else None


def nombre_de(afp) -> str:
    d = def_de(afp)
    return d["nombre"] if d else str(afp)


def fondos_de(afp) -> list[int]:
    """Fund types an AFP operates. Undeclared means all."""
    d = def_de(afp)
    if not d:
        return fondos()
    declared = d.get("fondos")
    return [int(f) for f in declared] if declared else fondos()


def opera(afp, fondo) -> bool:
    return int(fondo) in fondos_de(afp)


def afp_casa() -> str:
    """
    Display name of the house AFP: base of relative performance.
    Falls back to the first entry so the dashboard degrades instead
    of breaking if nobody declares casa.
    """
    for a in afps():
        if a.get("casa"):
            return a["nombre"]
    return afps()[0]["nombre"]


# ---- procode naming -------------------------------------------------

def procode(afp, fondo: int) -> str:
    """SPP_{CLAVE}_F{fondo}. Derived from the clave, never the name."""
    c = clave_de(afp)
    if not c:
        raise ValueError(f"AFP no registrada: {afp}. Agregala en config/afps.yaml.")
    return f"SPP_{c.upper()}_F{int(fondo)}"


def procode_bench(fondo: int) -> str:
    return f"SPP_BENCH_F{int(fondo)}"


def parse_procode(code: str) -> tuple[str, int] | None:
    """SPP_HABITAT_F2 -> ('habitat', 2). None if not an SPP fund procode."""
    parts = str(code or "").split("_")
    if len(parts) < 3 or parts[0] != "SPP" or not parts[-1].startswith("F"):
        return None
    clave = "_".join(parts[1:-1]).lower()
    if clave == "bench":
        return None
    try:
        return clave, int(parts[-1][1:])
    except ValueError:
        return None


# ---- DB registration ------------------------------------------------

def register_series(conn) -> int:
    """
    Idempotently registers every AFP x fund entity and its three series,
    plus the benchmark entities, directly as status='active'.

    Unlike the discovered SBS universe, this is a small closed set that
    afps.yaml declares in full, so there is no backfill-pending dance:
    the series exist from the moment the registry names them.

    Returns the number of NEW series_registry rows inserted.
    """
    from src.db.queries import get_or_create_entity_id

    inserted = 0

    def _serie(entity_id: int, field: str, source: str) -> int:
        cur = conn.execute(
            """
            INSERT INTO series_registry (
                entity_id, field, domain, source, frequency,
                default_start_date, status
            ) VALUES (%s, %s, 'prices', %s, 'daily', %s, 'active')
            ON CONFLICT (entity_id, field, source) DO NOTHING
            """,
            (entity_id, field, source, DEFAULT_START.isoformat()),
        )
        return 1 if cur.rowcount > 0 else 0

    for a in afps():
        for f in fondos_de(a["nombre"]):
            entity_id = get_or_create_entity_id(
                conn,
                procode=procode(a["clave"], f),
                entity_type="fund",
                name=f"{a['nombre']} Fondo {f}",
            )
            conn.execute(
                """
                INSERT INTO dim_security (entity_id, security_type)
                VALUES (%s, 'fund')
                ON CONFLICT (entity_id) DO NOTHING
                """,
                (entity_id,),
            )
            for field in METRICA_FIELD.values():
                inserted += _serie(entity_id, field, SOURCE_SBS)

    for f in fondos_benchmark():
        entity_id = get_or_create_entity_id(
            conn,
            procode=procode_bench(f),
            entity_type="index",
            name=f"Benchmark SPP Fondo {f}",
        )
        inserted += _serie(entity_id, "PX_LAST", SOURCE_BENCH)

    if inserted:
        logger.info(f"afps registry: {inserted} new series registered.")
    return inserted


def series_map(conn) -> dict[tuple[str, str], dict]:
    """
    (procode, field) -> series row for every SPP series (funds + bench).
    The runtime lookup transform and the web services share.
    """
    cur = conn.execute(
        """
        SELECT sr.series_id, sr.entity_id, sr.field, sr.source, e.procode, e.name
        FROM series_registry sr
        JOIN dim_entity e ON e.entity_id = sr.entity_id
        WHERE e.procode LIKE 'SPP\\_%' AND sr.domain = 'prices'
        """
    )
    return {(r["procode"], r["field"]): r for r in cur.fetchall()}
