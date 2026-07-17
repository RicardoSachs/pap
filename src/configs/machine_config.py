# src/configs/machine_config.py
# ---------------------------------------------------------------
# Loads machine-specific configuration from
# market_data_config.yaml.
#
# Falls  back to configs/machine_config.yaml if local file is
# not found, but logs a warning since the template has no values.
#
# All public functions are safe to call at import time.
# Config is loaded once and cached via lru_cache.
# ---------------------------------------------------------------

from src.shared.logging import setup_logging
from src.shared.paths import CONFIG_DIR

import os
import logging
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_LOCAL_CONFIG = (
    Path(os.path.expandvars('%USERPROFILE%'))
    / 'Documents'
    / 'Tools'
    / 'config'
    / 'market_data_config.yaml'
)
_BASE_CONFIG = CONFIG_DIR / 'machine_config.yaml'

@lru_cache(maxsize=1)
def get_machine_config() -> dict:
    """
    Loads and caches machine config from local yaml.
    Call this to access raw config dict if needed.
    Prefer the typed accessor functions below.
    
    :return: Machine config YAML as dictionary
    :rtype: dict
    """
    if _LOCAL_CONFIG.exists():
        path = _LOCAL_CONFIG
    else:
        path = _BASE_CONFIG
        logger.warning(
            'machine_config.local.yaml not found. '
            'Copy config/machine_config.yaml to '
            'configs/machine_config.local.yaml and fill in values '
            'for this machine before running any pipelines'
        )

    with open(path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    if not isinstance(cfg, dict):
        raise ValueError(f'Invalid machine config at {path} - expected a YAML mapping.')
    
    return cfg

# ---- Typed accessors ------------------------------------------

def machine_id() -> str:
    val = get_machine_config().get('machine_id', '')
    if not val:
        logger.warning(
            'machine_id not set in machine_config.local.yaml.'
        )
    return val or 'unknown'

def bloomberg_enabled() -> bool:
    return bool(get_machine_config().get('bloomberg_enabled', False))

def scraper_enabled() -> bool:
    return bool(get_machine_config().get('scraper_enabled', False))

def automated_scraper_enabled() -> bool:
    return bool(get_machine_config().get('automated_scraper_enabled', False))

def fms_enabled() -> bool:
    return bool(get_machine_config().get('fms_enabled', False))

def chromedriver_path() -> str | None:
    """
    Returns the absolute path to chromedriver.exe for this machine.
    Expands environmnet variables (e.g. %USERPROFILE%).
    Returns None if not set or scraper is not enabled.
    """
    val = get_machine_config().get('chromedriver_path', '')
    if not val:
        return None
    expanded = os.path.expandvars(val)
    path = Path(expanded)
    if not path.exists():
        logger.warning(
            f'chromedriver_path is set to {expanded} '
            'but the file does not exist. '
            'Download chromedrive.exe and place it at the path.'
        )
    return expanded

def timezone() -> str:
    return get_machine_config().get('timezone', 'America/Lima')

# ---- Capability guards ------------------------------------------

def assert_bloomberg() -> None:
    """
    Raises RuntimeError if Bloomberg is not enabled on this machine.
    Call at the top of any Bloomberg pipeline entry point.
    """
    if not bloomberg_enabled():
        raise RuntimeError(
            f'Bloomberg is not enabled on this machine ({machine_id()}). '
            'Set bloomberg_enabled: true in machine_config.local.yaml'
            'and ensure the Bloomberg BLP is installed to access the API.'
        )
    
def assert_fms() -> None:
    """
    Raises RuntimeError if FMS is not enabled on this machine.
    Call at the schedulers that contain FMS pipelines
    """
    if not fms_enabled():
        raise RuntimeError(
            f"FMS is not enabled on this machine ({machine_id()})"
            "Set fms_enabled: true in machine_config.local.yaml."
        )
    
def assert_scraper() -> None:
    """
    Raises RuntimeError if the scraper is not enabled on this machine.
    Call at the top of any acquisition script.
    """
    if not scraper_enabled():
        raise RuntimeError(
            f'Scraper is not enabled on this machine ({machine_id()}). '
            'Set scraper_enabled: true in machine_config.local.yaml.'
        )
    
    driver = chromedriver_path()
    if not driver:
        raise RuntimeError(
            'chromedriver_path is not set in machine_config.local.yaml. '
            'Download chromedriver.exe and set the path.'
        )
    
def assert_automated_scraper() -> None:
    """
    Raises RuntimeError if the automatic scraper is not enabled on this machine.
    Call at the top of any automatic acquisition script.
    """
    if not automated_scraper_enabled():
        raise RuntimeError(
            f'Automated scaper is not enabled on this machine ({machine_id()}). '
            f'Set automated_scraper_enabled: true in machine_config.local.yaml. '
        )
