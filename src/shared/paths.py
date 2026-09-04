# src/shared/paths.py
# ---------------------------------------------------------------
# Project path constants: resolves the data, config, seed and schema
# directories from the environment (defaults under the project root).

import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# ETL_DIR is the repo root. This file is at <repo>/src/shared/paths.py
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ETL_DIR = Path(__file__).resolve().parents[2]

# Main env dirs. DATA_DIR defaults to /data sibling of /<repo>
# overridden via .env when data lives elsewhere.
# `or` instead of getenv's default on purpose: .env.example ships the key
# empty (DATA_DIR=), and an empty string would otherwise win over the
# default, turning every data path relative to the CWD.
DATA_DIR = Path(os.getenv('DATA_DIR') or (PROJECT_ROOT / 'data'))

#ETL paths
CONFIG_DIR = ETL_DIR / 'config'
SEED_DIR = ETL_DIR / 'src' / 'seeds'
SCHEMA_DIR = ETL_DIR / 'src' / 'db' / 'schema'

#DATA paths
RAW_DIR = DATA_DIR / 'raw'
STAGING_DIR = DATA_DIR / 'staging'
#SEEDS_DIR = DATA_DIR / 'seeds'
LOGS_DIR = DATA_DIR / 'logs'
