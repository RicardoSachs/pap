
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Main env dirs
DATA_DIR = Path(os.getenv('DATA_DIR', PROJECT_ROOT / 'data'))
ETL_DIR = Path(os.getenv('ETL_DIR', PROJECT_ROOT / 'pgetl'))
#DB_PATH = Path(os.getenv('DB_PATH', PROJECT_ROOT / 'data' / 'db.sqlite')) TODO: errase later

#ETL paths
CONFIG_DIR = ETL_DIR / 'config'
SEED_DIR = ETL_DIR / 'src' / 'seeds'
SCHEMA_DIR = ETL_DIR / 'src' / 'db' / 'schema'

#DATA paths
RAW_DIR = DATA_DIR / 'raw'
STAGING_DIR = DATA_DIR / 'staging'
#SEEDS_DIR = DATA_DIR / 'seeds'
LOGS_DIR = DATA_DIR / 'logs'
