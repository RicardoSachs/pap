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
#
# The API does not touch the database schema at startup: the schema is
# applied by scripts/bootstrap_db.py (or scripts/crear_base.py on an office
# machine) and the SPP series are registered by the pipeline runs.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from web.api.routes import (benchmarks, contribution, formats, portfolios,
                            positions, prices, securities, spp, spp_write,
                            tasks)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Portfolio Analytics API", version="0.1.0")

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
app.include_router(spp_write.router)
app.include_router(benchmarks.router)
app.include_router(formats.router)
app.include_router(tasks.router)


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
        response = super().file_response(*args, **kwargs)
        path = str(getattr(response, "path", "")).replace("\\", "/")
        immutable = "/_next/static/" in path
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if immutable else "no-cache")
        return response


# Serve the built Next.js static export from / when it exists (post-build).
_BUNDLE = Path(__file__).resolve().parents[1] / "apps" / "dashboards" / "out"
if _BUNDLE.is_dir():
    app.mount("/", Bundle(directory=str(_BUNDLE), html=True), name="dashboards")
    logger.info(f"serving static bundle from {_BUNDLE}")
else:
    logger.info(f"no static bundle at {_BUNDLE} (dev mode -- use the Next dev server)")
