
import pandas as pd

from src.shared.paths import SEED_DIR

def load_series_seed() -> pd.DataFrame:
    df = pd.read_csv(SEED_DIR / 'series.csv', parse_dates=['default_start_date'])
    return df

def load_identifiers_seed() -> pd.DataFrame:
    df = pd.read_csv(SEED_DIR / 'identifiers.csv')
    return df
