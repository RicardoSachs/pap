
from pathlib import Path
import yaml

from src.shared.paths import CONFIG_DIR

def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f'Missing config file: {path}')
    with open(path, 'r') as f:
        return yaml.safe_load(f)
    
def load_securities() -> dict:
    '''
    Securities, identifiers and universes
    '''
    return _load_yaml(CONFIG_DIR / 'securities.yaml')

def load_series() -> dict:
    '''
    Series definitions (prices, fundamentals, cadence, default start)
    '''
    return _load_yaml(CONFIG_DIR / 'series.yaml')

def load_schedules() -> dict:
    '''
    Orchestration schedules
    '''
    return _load_yaml(CONFIG_DIR / 'schedules.yaml')

def load_all_configs() -> dict:
    '''
    Convenience loader for orchestrators
    '''
    return {
        'securities': load_securities(),
        'series': load_series(),
        'schedules': load_schedules
    }

def load_series_config(series_name:str) -> dict:
    '''
    Load configuration for a logical series / pipeline
    
    :param series_name: Description
    :type series_name: str
    :return: Description
    :rtype: dict
    '''

    cfg = _load_yaml(CONFIG_DIR / 'series.yaml')

    if series_name not in cfg:
        raise KeyError(f"Series '{series_name}' not found in series.yaml")
    
    return cfg[series_name]

def load_universe(universe_name: str) -> list[dict]:
    '''
    Load universe definition (list of securities)
    
    :param universe_name: Description
    :type universe_name: str
    :return: Description
    :rtype: list[dict]
    '''
    cfg = _load_yaml(CONFIG_DIR / 'universes.yaml')

    if universe_name not in cfg:
        raise KeyError(f"Universe '{universe_name}' not found in securities.yaml")
    
    return cfg[universe_name]

def load_pipelines() -> dict:
    '''
    Specific fields/values for pipelines
    '''
    return _load_yaml(CONFIG_DIR / 'pipelines.yaml')
