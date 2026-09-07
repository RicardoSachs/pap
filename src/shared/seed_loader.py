# src/shared/seed_loader.py
# ---------------------------------------------------------------
# Seed CSV loaders: reads the series, identifiers and portfolios seed
# files into pandas DataFrames.
#
# Missing or empty seed files return an EMPTY frame with the expected
# columns (with a WARNING) instead of raising - bootstrap/onboard then
# no-op that seed path and the SBS discovery registry remains the only
# live writer. pd.read_csv raises EmptyDataError on 0-byte files, which
# would otherwise crash bootstrap at step 0.

import logging
from pathlib import Path

import pandas as pd

from src.shared.paths import SEED_DIR

logger = logging.getLogger(__name__)

SERIES_COLUMNS = [
    'procode', 'entity_type', 'name', 'field', 'domain', 'source',
    'frequency', 'default_start_date', 'status', 'security_type',
    'release_pattern', 'release_lag_days', 'allow_revisions',
    'revision_lookback',
]

IDENTIFIERS_COLUMNS = [
    'procode', 'entity_type', 'id_type', 'id_value', 'source', 'is_primary',
]

PORTFOLIOS_COLUMNS = [
    'procode', 'source', 'portfolio_type', 'display_name',
    'base_currency', 'status',
]


def _read_seed(path: Path, columns: list[str], **kwargs) -> pd.DataFrame:
    try:
        return pd.read_csv(path, **kwargs)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        logger.warning(
            f'{path.name} missing or empty - returning empty seed frame; '
            f'this seed path will register nothing.'
        )
        return pd.DataFrame(columns=columns)


def load_series_seed() -> pd.DataFrame:
    return _read_seed(
        SEED_DIR / 'series.csv', SERIES_COLUMNS,
        parse_dates=['default_start_date'],
    )


def load_identifiers_seed() -> pd.DataFrame:
    return _read_seed(SEED_DIR / 'identifiers.csv', IDENTIFIERS_COLUMNS)


def load_portfolios_seed() -> pd.DataFrame:
    return _read_seed(
        SEED_DIR / 'portfolios.csv', PORTFOLIOS_COLUMNS,
        dtype={'procode': str},
        comment='#',
    )
