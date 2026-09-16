# src/pipelines/prices/sbs/registry.py
# ---------------------------------------------------------------
# Single registry of SBS price sub-pipelines, shared by
# scripts/run_prices.py (CLI) and scripts/scheduler.py (daily job)
# so the two can never drift.
#
# Each value is the dotted path of a module exposing
# run(run_date: date | None, series_override: list[dict] | None).
# ---------------------------------------------------------------

import importlib
import logging
from datetime import date

logger = logging.getLogger(__name__)

SBS_PIPELINES: dict[str, str] = {
    "vector_completo": "src.pipelines.prices.sbs.vector_completo.run",
    "rf_local":        "src.pipelines.prices.sbs.rf_local.run",
    "rf_exterior":     "src.pipelines.prices.sbs.rf_exterior.run",
    "tipo_cambio":     "src.pipelines.prices.sbs.tipo_cambio.run",
    "dividendos":      "src.pipelines.prices.sbs.dividendos.run",
}


def run_sbs_pipelines(
    run_date: date | None = None,
    series_override: list[dict] | None = None,
    file_type: str | None = None,
) -> None:
    """
    Runs one SBS sub-pipeline (file_type given) or all of them.
    Each sub-pipeline gates itself on the SBS reporting calendar,
    so calling this on a non-reporting day is a cheap no-op.
    """
    to_run = (
        {file_type: SBS_PIPELINES[file_type]}
        if file_type
        else SBS_PIPELINES
    )
    for name, module_path in to_run.items():
        logger.info(f"--- SBS pipeline: {name} ---")
        mod = importlib.import_module(module_path)
        mod.run(run_date=run_date, series_override=series_override)
