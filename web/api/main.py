
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
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from web.api.routes import contribution, portfolios, positions, prices, securities

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


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# Serve the built Next.js static export from / when it exists (post-build).
_BUNDLE = Path(__file__).resolve().parents[1] / "apps" / "dashboards" / "out"
if _BUNDLE.is_dir():
    app.mount("/", StaticFiles(directory=str(_BUNDLE), html=True), name="dashboards")
    logger.info(f"serving static bundle from {_BUNDLE}")
else:
    logger.info(f"no static bundle at {_BUNDLE} (dev mode -- use the Next dev server)")

