
# web/api/main.py
# ---------------------------------------------------------------------------
# FastAPI app for the analytics dashboards.
# ---------------------------------------------------------------------------
# Serves BOTH the JSON API (/api/...) and the built Next.js static bundle on
# the same origin -- relative /api URLs in the front end then need no CORS.
#
# Run (dev):  uvicorn web.api.main:app --reload --port 8000   (repo root on PYTHONPATH)
# The Next.js dev server (port 3000) proxies /api here via next.config rewrites.
# For an integrated test, build the bundle (npm run build) so out/ exists and is
# served from / below.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from web.api.routes import (contribution, formatos, portfolios, positions,
                            prices, tradebook,
                            securities, spp, spp_bloomberg, spp_carga)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Converges the database on startup: applies the schema files, then
    registers the SPP series.

    Both steps are idempotent (CREATE TABLE IF NOT EXISTS, plus the
    convergence ALTERs in 56_spp_migraciones.sql, and 51 upserts), and
    both exist for the machine that installs this project from a zip:
    updating means unzipping a newer copy, with no migration step a
    person could forget. Without the registration, a freshly created
    database yields a tablero that opens and reads empty but refuses
    every write with "no hay serie registrada - corre
    run_sbs_valor_cuota.py --solo-registro", a step nothing in the UI
    mentions.

    A failure here must NEVER stop the API from starting: the tablero
    is also how the operator finds out what is wrong, and an API that
    refuses to boot can only say it through a console they may not be
    looking at.
    """
    try:
        from src.db.bootstrap import create_schema
        from src.db.connection import get_connection
        with get_connection() as conn:
            create_schema(conn)
    except Exception as exc:
        logger.warning(f"schema check skipped at startup: {exc}")
    try:
        from src.pipelines.prices.sbs.valor_cuota.run import ensure_registered
        ensure_registered()
    except Exception as exc:
        logger.warning(f"SPP series registration skipped at startup: {exc}")
    yield


app = FastAPI(title="Portfolio Analytics API", version="0.1.0", lifespan=lifespan)

# Dev convenience: allow the Next dev server (localhost:3000) to call the API
# directly. In production the bundle is same-origin, so this is harmless.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(securities.router)
app.include_router(prices.router)
app.include_router(portfolios.router)
app.include_router(positions.router)
app.include_router(contribution.router)
app.include_router(spp.router)
app.include_router(spp_bloomberg.router)
app.include_router(spp_carga.router)
app.include_router(tradebook.router)
app.include_router(formatos.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


class Bundle(StaticFiles):
    """
    StaticFiles that states a cache policy instead of leaving it to the
    browser's guess.

    Starlette sends only last-modified/etag, so browsers apply heuristic
    freshness (a fraction of the file's age) and serve a CACHED
    index.html without revalidating - which is why every rebuild used to
    need a Ctrl+F5 to be seen. The split is the one the bundle's own
    naming makes safe: /_next/static/* filenames carry a content hash
    and can be cached forever, while the HTML entry points must be
    revalidated on every navigation.
    """

    def file_response(self, *args, **kwargs):
        respuesta = super().file_response(*args, **kwargs)
        ruta = str(getattr(respuesta, "path", "")).replace("\\", "/")
        inmutable = "/_next/static/" in ruta
        respuesta.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if inmutable
            else "no-cache")
        return respuesta


# The brand mark lives in the source tree, not in the build output, and is
# served straight from there. That is the whole point: the machines that run
# this have no Node, so anything that needed a rebuild to appear would in
# practice need a trip back to a developer. Dropping a file in the folder is
# something the operator can do alone.
_MARCA = Path(__file__).resolve().parents[1] / "apps" / "dashboards" / "public" / "marca"
_IMAGENES = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"}


@app.get("/api/marca")
def marca():
    """
    Whatever image is in public/marca, if any.

    Asking instead of guessing a filename is what lets the sidebar stay
    clean when there is no logo: a fixed <img src> would have to try and
    fail, and every page load would leave 404s in this same log - the log
    the operator reads when something is actually wrong.

    The name decides the slot, because the two are not the same picture at
    two sizes: collapsed the bar is 48px and only a symbol fits, expanded
    it is 180px and the full lockup fits. Anything else is the lockup.
    """
    if not _MARCA.is_dir():
        return {"simbolo": None, "lockup": None}
    archivos = sorted(f for f in _MARCA.iterdir()
                      if f.is_file() and f.suffix.lower() in _IMAGENES)
    simbolo = next((f for f in archivos if "simbolo" in f.stem.lower()), None)
    lockup = next((f for f in archivos if f is not simbolo), None)
    return {
        "simbolo": f"/marca/{simbolo.name}" if simbolo else None,
        "lockup": f"/marca/{lockup.name}" if lockup else None,
    }


# Serve the built Next.js static export from / when it exists (post-build).
_BUNDLE = Path(__file__).resolve().parents[1] / "apps" / "dashboards" / "out"
if _MARCA.is_dir():
    # Registered BEFORE the catch-all "/" so it wins, and so the file the
    # operator dropped is served even though out/ has a stale copy from the
    # last build.
    app.mount("/marca", Bundle(directory=str(_MARCA)), name="marca")
if _BUNDLE.is_dir():
    app.mount("/", Bundle(directory=str(_BUNDLE), html=True), name="dashboards")
    logger.info(f"serving static bundle from {_BUNDLE}")
else:
    logger.info(f"no static bundle at {_BUNDLE} (dev mode -- use the Next dev server)")

