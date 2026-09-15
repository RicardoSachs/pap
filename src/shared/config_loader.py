# src/shared/config_loader.py
# ---------------------------------------------------------------
# YAML config loaders for the config/ directory.
# Only files with live consumers have loaders:
#   schedules.yaml -> scripts/scheduler.py
#   pipelines.yaml -> src/pipelines/dim/bloomberg/security/run.py
# Series/universe definitions live in series_registry (seeded from
# src/seeds/), not in YAML.

from pathlib import Path
import yaml

from src.shared.paths import CONFIG_DIR

def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f'Missing config file: {path}')
    with open(path, 'r') as f:
        return yaml.safe_load(f)

def load_schedules() -> dict:
    """
    Scheduler job fire times (cron fields per job id)
    """
    return _load_yaml(CONFIG_DIR / 'schedules.yaml')

def load_pipelines() -> dict:
    """
    Specific fields/values for pipelines
    """
    return _load_yaml(CONFIG_DIR / 'pipelines.yaml')
