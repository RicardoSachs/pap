# src/scrapers/sbs.py
# ---------------------------------------------------------------
# SBS website scraper (Selenium): downloads the SBS 'vector de precios' and
# related xls files into the raw data tree, keyed by reporting date.

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from src.shared.env import optional
from src.shared.paths import RAW_DIR
from src.configs.machine_config import chromedriver_path

import logging
import time
from datetime import datetime, date, timedelta
from urllib.parse import urljoin

from pathlib import Path
from typing import Optional
import shutil
import os
import sys
import errno

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

VP_SBS_DIR = RAW_DIR / 'sbs' / 'vector_precios'

# Legacy landing directory: a network share, so it is site-specific and
# lives in .env (SBS_LEGACY_DIR), never in source. None when unset - the
# --legacy paths simply are not available on a machine that has not set it.
_legacy = optional('SBS_LEGACY_DIR')
VP_SBS_DIR_LEGACY = Path(_legacy) if _legacy else None

SBS_BASE_URL = 'https://extranet.sbs.gob.pe/vectorprecios/'

SBS_FILES = {
    'vector_completo': {
        'folder':'vector_completo',
        'url_landing': 'vector/IrVerVectorCompleto.arb?propositoPagina=limpiar&codigoAplicacion=132&codigoOpcion=18',
        'url_download':'vector/IrVerVectorCompleto.do?codigoAplicacion=132&criteriosVectorComp.campo1={0}%2F{1}%2F{2}&criteriosVectorComp.campo2=&criteriosVectorComp.campo3=&criteriosVectorComp.campo4=&criteriosVectorComp.campo5=&d-7318065-e=2&6578706f7274=1&codigoOpcion=18',
        'fecha_dropdown_name':'criteriosVectorComp.campo1',
        'fecha_minima':'24/09/2012',
        'ningun_resultado_enabled': False
    },
    'rf_local': {
        'folder':'rfl',
        'url_landing':'vector/IrVerRentaFijaLocal.arb?propositoPagina=limpiar&codigoAplicacion=132&codigoOpcion=23',
        'url_download':'vector/IrVerRentaFijaLocal.do?codigoAplicacion=132&criteriosRentFijLocal.campo1={0}%2F{1}%2F{2}&criteriosRentFijLocal.campo2=&d-7318065-e=2&criteriosRentFijLocal.campo5=&criteriosRentFijLocal.campo3=&criteriosRentFijLocal.campo4=&6578706f7274=1&codigoOpcion=23',
        'fecha_dropdown_name':'criteriosRentFijLocal.campo1',
        'fecha_minima':'24/09/2012',
        'ningun_resultado_enabled': False
    },
    'rf_exterior': {
        'folder':'rfe',
        'url_landing':'vector/IrVerRentaFijaExt.arb?propositoPagina=limpiar&codigoAplicacion=132&codigoOpcion=22',
        'url_download':'vector/IrVerRentaFijaExt.do?codigoAplicacion=132&d-7318065-e=2&criteriosRentFijExt.campo5=&6578706f7274=1&criteriosRentFijExt.campo1={0}%2F{1}%2F{2}&codigoOpcion=22&criteriosRentFijExt.campo2=&criteriosRentFijExt.campo3=&criteriosRentFijExt.campo4=',
        'fecha_dropdown_name':'criteriosRentFijExt.campo1',
        'fecha_minima':'08/05/2014',
        'ningun_resultado_enabled': False
    },
    'tipo_cambio': {
        'folder':'tc',
        'url_landing':'vector/IrVerTiposCambio.arb?propositoPagina=limpiar&codigoAplicacion=132&codigoOpcion=24',
        'url_download':'vector/IrVerTiposCambio.do?codigoAplicacion=132&criteriosTipoCambio.campo3=&criteriosTipoCambio.campo4=&d-7318065-e=2&6578706f7274=1&criteriosTipoCambio.campo1={0}%2F{1}%2F{2}&codigoOpcion=24&criteriosTipoCambio.campo2={0}%2F{1}%2F{2}',
        'fecha_dropdown_name':'criteriosTipoCambio.campo1',
        'fecha_minima':'24/09/2012',
        'ningun_resultado_enabled': False
    },
    'dividendos': {
        'folder':'dividendos',
        'url_landing':'reportes/IrReporteDividendos.arb?propositoPagina=limpiar&codigoAplicacion=132&codigoOpcion=16',
        'url_download':'reportes/IrReporteDividendos.do?codigoAplicacion=132&d-2439070-e=2&criteriosRepDivDto.campo10=2&6578706f7274=1&criteriosRepDivDto.campo4={0}%2F{1}%2F{2}&codigoOpcion=16',
        'fecha_dropdown_name':'criteriosRepDivDto.campo4',
        'fecha_minima':'24/09/2012',
        'ningun_resultado_enabled': True
    }
}

SBS_FILES_LEGACY = {
    'vector_completo': {
        'folder':'Vector completo',
        'postfix': '',
        'url_landing': 'vector/IrVerVectorCompleto.arb?propositoPagina=limpiar&codigoAplicacion=132&codigoOpcion=18',
        'url_download':'vector/IrVerVectorCompleto.do?codigoAplicacion=132&criteriosVectorComp.campo1={0}%2F{1}%2F{2}&criteriosVectorComp.campo2=&criteriosVectorComp.campo3=&criteriosVectorComp.campo4=&criteriosVectorComp.campo5=&d-7318065-e=2&6578706f7274=1&codigoOpcion=18',
        'fecha_dropdown_name':'criteriosVectorComp.campo1',
        'fecha_minima':'24/09/2012',
        'ningun_resultado_enabled': False
    },
    'rf_local': {
        'folder':'RF',
        'postfix': ' RFL',
        'url_landing':'vector/IrVerRentaFijaLocal.arb?propositoPagina=limpiar&codigoAplicacion=132&codigoOpcion=23',
        'url_download':'vector/IrVerRentaFijaLocal.do?codigoAplicacion=132&criteriosRentFijLocal.campo1={0}%2F{1}%2F{2}&criteriosRentFijLocal.campo2=&d-7318065-e=2&criteriosRentFijLocal.campo5=&criteriosRentFijLocal.campo3=&criteriosRentFijLocal.campo4=&6578706f7274=1&codigoOpcion=23',
        'fecha_dropdown_name':'criteriosRentFijLocal.campo1',
        'fecha_minima':'24/09/2012',
        'ningun_resultado_enabled': False
    },
    'rf_exterior': {
        'folder':'RF',
        'postfix': ' RFE',
        'url_landing':'vector/IrVerRentaFijaExt.arb?propositoPagina=limpiar&codigoAplicacion=132&codigoOpcion=22',
        'url_download':'vector/IrVerRentaFijaExt.do?codigoAplicacion=132&d-7318065-e=2&criteriosRentFijExt.campo5=&6578706f7274=1&criteriosRentFijExt.campo1={0}%2F{1}%2F{2}&codigoOpcion=22&criteriosRentFijExt.campo2=&criteriosRentFijExt.campo3=&criteriosRentFijExt.campo4=',
        'fecha_dropdown_name':'criteriosRentFijExt.campo1',
        'fecha_minima':'08/05/2014',
        'ningun_resultado_enabled': False
    },
    'tipo_cambio': {
        'folder':'TC',
        'postfix': ' TC',
        'url_landing':'vector/IrVerTiposCambio.arb?propositoPagina=limpiar&codigoAplicacion=132&codigoOpcion=24',
        'url_download':'vector/IrVerTiposCambio.do?codigoAplicacion=132&criteriosTipoCambio.campo3=&criteriosTipoCambio.campo4=&d-7318065-e=2&6578706f7274=1&criteriosTipoCambio.campo1={0}%2F{1}%2F{2}&codigoOpcion=24&criteriosTipoCambio.campo2={0}%2F{1}%2F{2}',
        'fecha_dropdown_name':'criteriosTipoCambio.campo1',
        'fecha_minima':'24/09/2012',
        'ningun_resultado_enabled': False
    },
    'dividendos': {
        'folder':'Dividendos',
        'postfix': ' D',
        'url_landing':'reportes/IrReporteDividendos.arb?propositoPagina=limpiar&codigoAplicacion=132&codigoOpcion=16',
        'url_download':'reportes/IrReporteDividendos.do?codigoAplicacion=132&d-2439070-e=2&criteriosRepDivDto.campo10=2&6578706f7274=1&criteriosRepDivDto.campo4={0}%2F{1}%2F{2}&codigoOpcion=16',
        'fecha_dropdown_name':'criteriosRepDivDto.campo4',
        'fecha_minima':'24/09/2012',
        'ningun_resultado_enabled': True
    },
    'alternativos': {
        'folder':'Alternativos',
        'postfix': ' Alts',
        'url_landing':'reportes/IrReporteActFonAltern.arb?propositoPagina=limpiar&codigoAplicacion=132&codigoOpcion=13',
        'url_download':'reportes/IrReporteActFonAltern.do?codigoAplicacion=132&criteriosRepActFonAlt.campo1=&criteriosRepActFonAlt.campo2=&criteriosRepActFonAlt.campo3={0}%2F{1}%2F{2}&criteriosRepActFonAlt.campo4={0}%2F{1}%2F{2}&d-7318065-e=2&6578706f7274=1&codigoOpcion=13',
        'fecha_dropdown_name':'criteriosRepActFonAlt.campo3',
        'fecha_minima':'24/09/2012',
        'ningun_resultado_enabled': True
    },
    'fondos_inversion': {
        'folder':'Fondos inversion',
        'postfix': ' FI',
        'url_landing':'reportes/IrReporteActFonInversion.arb?propositoPagina=limpiar&codigoAplicacion=132&codigoOpcion=14',
        'url_download':'reportes/IrReporteActFonInversion.do?codigoAplicacion=132&criteriosRepActFonInv.campo2=&criteriosRepActFonInv.campo1=&criteriosRepActFonInv.campo4={0}%2F{1}%2F{2}&criteriosRepActFonInv.campo3={0}%2F{1}%2F{2}&d-7318065-e=2&6578706f7274=1&codigoOpcion=14',
        'fecha_dropdown_name':'criteriosRepActFonInv.campo3',
        'fecha_minima':'24/09/2012',
        'ningun_resultado_enabled': True
    }
}


def acquire_day(
    run_date: date,
    file_types: Optional[list[str]] = None,
    timeout_seconds: int = 720,
    max_retries: int = 5,
    retry_delay: int = 10,
    raw_dir: Optional[Path] = None,
    sbs_files: Optional[list[dict]] = None,
    force: bool = False,
) -> dict[str, bool]:
    # Resolve files to download:
    download_dir = _resolve_raw_dir(raw_dir)

    files_to_download = _resolve_file_types(file_types, sbs_files)
    if not files_to_download:
        return {}
    
    logger.info(
        f"=== SBS acquire_day | date={run_date} | "
        f"files={[f for f in files_to_download.keys()]} ==="
    )

    results = {}

    # Launch chrome(driver)
    driver = create_driver(download_dir)

    # Navigate to login
    driver.get('https://extranet.sbs.gob.pe/app/login.jsp')

    # Wait for manual login -poll for post-login indicator
    logger.info(
        f'Waiting up to {timeout_seconds}s for manual login. '
        f'Please complete the login authentication in the browser.'
    )

    logged_in = _wait_for_login(driver, timeout_seconds=timeout_seconds)

    if not logged_in:
        logger.error(
            f'Login not detected after {timeout_seconds}s. Aborting.'
        )
        driver.close()
        sys.exit(1)
        return {f: False for f in files_to_download.keys()}

    logger.info('Login detected. Starting file downloads.')

    try:
        day_results = _download_day(
            driver,
            run_date=run_date,
            files_to_download=files_to_download,
            max_retries=max_retries,
            retry_delay=retry_delay,
            raw_dir=raw_dir,
            force=force
        )

        # Convert to {name: bool} for daily caller convenience
        results = {
                name: (status in ("ok", "skipped"))
                for name, status in day_results.items()
            }

    finally:
        _close_sbs_portal(driver)
        driver.close()

    return results

def acquire_range(
    start_date: date,
    end_date: date,
    file_types: Optional[list[str]] = None,
    timeout_seconds: int = 720,
    max_retries: int = 10,
    retry_delay: int = 10,
    raw_dir: Optional[Path] = None,
    sbs_files: Optional[list[dict]] = None,
    force: bool = False
) -> dict[str, list[date]]:
    """
    Acquires missing SBS files across a date range.
    Opens a single browser session for the entire range.

    Steps:
      1. Login once (manual image pad)
      2. Query portal select element for eligible dates in range
      3. Diff eligible dates against data/raw/ filesystem
      4. Download missing files with per-file retry logic

    Returns:
        {
            "succeeded": [date, ...],  all files downloaded OK
            "failed":    [date, ...],  at least one file failed
            "skipped":   [date, ...],  all files already in raw/
        }
    
    """
    # Resolve files to download:
    files_to_download = _resolve_file_types(file_types, sbs_files)
    if not files_to_download:
        return {'succeeded': [], 'failed': [], 'skipped': []}
    
    succeeded = []
    failed = []
    skipped = []

    logger.info(
        f"=== SBS acquire_range | "
        f"{start_date} to {end_date} | "
        f"files={[f for f in files_to_download.keys()]} | "
        f"max_retries={max_retries} ==="
    )

     # Launch chrome(driver)
    driver = create_driver(VP_SBS_DIR)

    # Step 1: login once
    driver.get('https://extranet.sbs.gob.pe/app/login.jsp')

    # Wait for manual login -poll for post-login indicator
    logger.info(
        f'Waiting up to {timeout_seconds}s for manual login. '
        f'Please complete the login authentication in the browser.'
    )

    logged_in = _wait_for_login(driver, timeout_seconds=timeout_seconds)

    if not logged_in:
        logger.error(
            f'Login not detected after {timeout_seconds}s. Aborting bulk acquisition.'
        )
        driver.close()
        sys.exit(1)
        return {'succeeded': [], 'failed': [], 'skipped': []}

    logger.info('Login detected. Starting file downloads.')
    
    # Step 2: query portal for eligible dates inside the session
    logger.info('Querying portal for available dates.')
    eligible_dates = _get_eligible_dates(driver, start_date, end_date)

    if not eligible_dates:
        logger.warning('No eligible dates found in portal for given range.')
        _close_sbs_portal(driver)
        driver.close()
        return {'succeeded': [], 'failed': [], 'skipped': []}
    
    logger.info(f'{len(eligible_dates)} eligible dates found in portal.')

    # Step 3: diff against filesystem
    dates_to_download = _diff_against_raw(eligible_dates, files_to_download, raw_dir)

    if not dates_to_download:
        logger.info('All eligible dates already in raw/. Nothing to download.')
        _close_sbs_portal(driver)
        driver.close()
        return {'successed':[], 'failed':[], 'skipped':eligible_dates}
    
    logger.info(
        f'{len(dates_to_download)} dates missing from raw/. '
        f'{len(eligible_dates) - len(dates_to_download)}'
    )
    skipped = [d for d in eligible_dates if d not in dates_to_download]

    # Step 4: download with retry
    for run_date in dates_to_download:
        day_results = _download_day(
            driver,
            run_date=run_date,
            files_to_download=files_to_download,
            max_retries=max_retries,
            retry_delay=retry_delay,
            raw_dir=raw_dir,
            force=force
        )

        statuses = list(day_results.values())
        if all(s == 'skipped' for s in statuses):
            skipped.append(run_date)
        elif any(s == 'failed' for s in statuses):
            failed.append(run_date)
            logger.warning(f'{run_date}: partial failure - {day_results}')
        else:
            succeeded.append(run_date)
            logger.info(f'{run_date}: all files OK.')

    _close_sbs_portal(driver)
    driver.close()

    logger.info(
        f'Range complete: {len(succeeded)} succeeded, '
        f'{len(failed)} failed, {len(skipped)} skipped.'
    )

    if failed:
        logger.warning(
            f'Failed dates: {[str(d) for d in sorted(failed)]}. '
            f'Re-run scoped to these dates to retry.'
        )

    return {'succeeded': succeeded, 'failed': failed, 'skipped': skipped}

def find_latest_file(folder_name: str, run_date: date, raw_dir: Optional[Path] = None) -> Optional[Path]:
    """
    Finds the most recent .xls file in data/raw/sbs/vector_precios/{file_type}/
    up to and including run_date.
    Used by check_sbs.py and ingestion pipeline extract.py
    Returns None if no file found.
    
    :param folder_name: Vector folder name (vector_completo, tc, rfl, etc.)
    :type folder_name: str
    """
    download_dir = _resolve_raw_dir(raw_dir)
    search_dir = download_dir / folder_name
    if not search_dir.exists():
        logger.warning(f'SBS raw dir does not exist: {search_dir}')
        return None
    
    files = sorted(search_dir.glob('*.xls'), reverse = True)
    if not files:
        logger.warning(f'No SBS files found in {search_dir}')
        return None
    
    cutoff = run_date.strftime('%Y%m%d')
    target = next(
        (f for f in files if f.stem[:8] <= cutoff),
        None
    )

    if target is None:
        logger.warning('No SBS file on or before {run_date} in {search_dir}')
    else:
        logger.info(f'Found SBS file in {folder_name}: {target.name}')

    return target

def _wait_for_login(driver, timeout_seconds: int) -> bool:
    """
    Polls the page every 3 seconds waiting for a post-login indicator.
    Adjust the selector to match whatever element appears after
    successful SBS login. (e.g. a nav menu, username display, dashboard).
    
    :param driver: selenium.webdriver
    :param timeout_seconds: Max time until stops
    :type timeout_seconds: int
    :return: True if success, False otherwise
    :rtype: bool
    """
    poll_interval = 3
    elapsed = 0

    while elapsed < timeout_seconds:
        try:
            # Adjust selector to a reliable post-login element on SBS
            WebDriverWait(driver, poll_interval)\
                .until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'img[src="images/producto00135.gif"]')
                ))
            driver.find_element(By.CSS_SELECTOR, 'img[src="images/producto00135.gif"]').click()
            return True
        except Exception:
            elapsed += poll_interval
            remaining = timeout_seconds - elapsed
            if remaining > 0:
                logger.info(f'Waiting for login... {remaining}s remaining.')
    
    return False

def _download_file(
    driver: webdriver.Chrome, 
    fecha_str: str, 
    file_key: str,
    file_postfix: str, 
    download_dir: Path, 
    nombre_folder: str, 
    ningun_resultado: bool,
    dropdown_name: str, 
    download_url: str,
    landing_url: str,
    timeout: float = 30.0,
    ) -> bool:

    """
    Download and move xls vector de precios to data/raw/sbs/vector_precios.
    Works for [rfl, rfe, vector_completo].
    Returns True if successfully downloaded the vector, False otherwise.

    :param fecha_str: Date in format "%d/%m/%Y"
    :type fecha_str: str
    :param download_path: Root path of folders location
    :type download_path: str
    :param nombre_folder: Folder file type name
    :type nombre_folder: str
    :param ningun_resultado: Indicates if query can return null tables in webpage
    :type ningun_resultado: bool
    :param dropdown_name: HTML name (ID) of dropdown list
    :type dropdown_name: str
    :param download_url: URL to download per file type x date
    :type download_url: str
    """

    fecha = datetime.strptime(fecha_str, '%d/%m/%Y')
    nombre_xls = fecha.strftime("%Y%m%d") + file_postfix + '.xls'

    output_dir = download_dir / nombre_folder
    output_path = output_dir / nombre_xls

    # Commented: file existence is done by _download_day
    # if output_path.exists():
    #     logger.info(f'{nombre_folder}: already exists, skipping.')
    #     return True

    try:
        logger.info(f'Downloading {nombre_folder}/{nombre_xls}')

        # Go to landing page
        driver.get(f'{SBS_BASE_URL}{landing_url}')

        # Set the date and search
        fecha_dropdown = wait_and_click(driver, By.NAME, dropdown_name)
        fecha_select = Select(fecha_dropdown)
        fecha_select.select_by_visible_text(fecha_str)
        
        # Handle TC double date list
        # if driver.find_elements(By.NAME, 'criteriosTipoCambio.campo2'):
        #     fecha_dropdown2 = wait_and_click(driver, By.NAME, 'criteriosTipoCambio.campo2')
        #     fecha_select2 = Select(fecha_dropdown2)
        #     fecha_select2.select_by_visible_text(fecha_str)

        # Handle second date selector
        boton2_names = [
            'criteriosTipoCambio.campo2', 
            'criteriosRepActFonAlt.campo4',
            'criteriosRepActFonInv.campo4']

        fecha_dropdown2_list = []
        for name in boton2_names:
            fecha_dropdown2_list.extend(driver.find_elements(By.NAME, name))

        if fecha_dropdown2_list:
            fecha_select2 = Select(fecha_dropdown2_list[0])
            fecha_select2.select_by_visible_text(fecha_str)

        buscar_button = driver.find_elements(By.CLASS_NAME, 'boton')[-1] # use the last button, for the Dividendos report
        buscar_button.click()

        # Download xls
        WebDriverWait(driver, timeout).until( # wait for the results table or the "no results" message
                EC.any_of(
                    EC.presence_of_element_located((By.ID, 'genericoDto')),
                    EC.presence_of_element_located((By.ID, 'genericDto')),
                    EC.presence_of_element_located((By.XPATH, 
                                                    "//td[contains(., 'Ningún resultado coincide con sus criterios de búsqueda.')]"))
                )
            )
            
        if driver.find_elements(By.XPATH, "//td[contains(., 'Ningún resultado coincide con sus criterios de búsqueda.')]"):
            #if nombre_folder == 'dividendos':
            if ningun_resultado:
                _save_empty_file(nombre_xls, output_dir, file_key)
            else:
                logger.info(f'{nombre_folder}: returned no matching results, skipping.')
            return True

        # Wait for the download to finish
        prev_files = snapshot_files(download_dir)

        driver.get(f'{SBS_BASE_URL}{fecha_url(fecha, download_url)}') # Trigger download
        wait_for_new_download(download_dir, prev_files, timeout)

        # Validate the file is not empty
        if is_file_empty(download_dir / 'excel.xls'):
            raise TypeError('Empty file')

        # Rename xls with the date
        os.rename(
            download_dir / 'excel.xls',
            download_dir / nombre_xls
        )

        # Move to its folder
        shutil.move(
            download_dir / nombre_xls,
            output_path
        )

        logger.info(f'{nombre_folder}: saved to {output_path}')

        return True
    
    except Exception as e:
        logger.error(f'{nombre_folder}: download failed - {e}')
        return False
    
    finally:
        for file in os.listdir(download_dir):
            if file.endswith('.xls') or file.endswith('.crdownload'):
                silent_remove(download_dir / file)

def _download_day(
    driver: webdriver.Chrome,
    run_date: date,
    files_to_download: dict,
    max_retries: int,
    retry_delay: int,
    raw_dir: Optional[Path] = None,
    force: bool = False,
) -> dict[str, str]:
    """
    Downloads all files for a single day with per-file retry logic.
    Shared by both acquire_day and acquire_range.

    Returns dict {file_name: "ok" | "skipped" | "failed"} per file.
    "skipped" means the file already existed on disk before attempting.
    """
    donwload_dir = _resolve_raw_dir(raw_dir)

    results = {}

    for file_name, file_cfg in files_to_download.items():
        
        output_path = donwload_dir / file_cfg['folder'] / (run_date.strftime("%Y%m%d") + file_cfg.get('postfix','') + '.xls')
        
        if not force and output_path.exists():
            results[file_name] = "skipped"
            logger.info(f"{file_name} {run_date}: already exists, skipping.")
            continue

        success = False
        for attempt in range(1, max_retries + 1):
            success = _download_file(
                driver,
                fecha_str=run_date.strftime('%d/%m/%Y'),
                file_key=file_name,
                file_postfix=file_cfg.get('postfix',''),
                download_dir=donwload_dir,
                nombre_folder=file_cfg['folder'],
                ningun_resultado=file_cfg['ningun_resultado_enabled'],
                dropdown_name=file_cfg['fecha_dropdown_name'],
                download_url=file_cfg['url_download'],
                landing_url=file_cfg['url_landing']
            )
            if success:
                break
            if attempt < max_retries:
                logger.warning(
                    f"{file_name} {run_date}: "
                    f"attempt {attempt}/{max_retries} failed, "
                    f"retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
            else:
                logger.error(
                    f"{file_name} {run_date}: "
                    f"all {max_retries} attempts failed."
                )

        results[file_name] = "ok" if success else "failed"

    return results

def _close_sbs_portal(driver) -> None:
    driver.get('https://extranet.sbs.gob.pe/vectorprecios/salir.do')
    salir_button_list = driver.find_elements(By.CSS_SELECTOR, 'img[src="images/salir1.gif"]')
    if salir_button_list:
        salir_button_list[0].click()

def silent_remove(filepath):
    try:
        os.remove(filepath)
    except OSError as e:
        if e.errno != errno.ENOENT: # errno.ENOENT = no such file or directory
            raise

def fecha_url(fecha_dt, base_url) -> str:
    """
    Build the download URL for a given date.
    
    :param fecha_dt: datetime of the date
    :param base_url: base URL of the platform
    :return: download URL for that date
    :rtype: str
    """
    d = '{:02d}'.format(fecha_dt.day)
    m = '{:02d}'.format(fecha_dt.month)
    Y = fecha_dt.year

    url = base_url.format(d,m,Y)

    return url

def create_driver(download_dir):
    # Driver path comes from machine_config (per-machine, outside the repo).
    service = Service(chromedriver_path(), log_output="NUL")

    # Opciones del navegador
    options = Options()
    
    prefs = {
        'download.default_directory': str(download_dir),
        'download.prompt_for_download': False,
        'download.directory_upgrade': True,
        'safebrowsing.enabled': True,
        'excludeSwitches': 'enable-logging'
    }

    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--log-level=3')
    options.add_experimental_option('prefs', prefs)

    return webdriver.Chrome(options=options, service=service)

def wait_and_click(driver, by, value, timeout = 10):
    element = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, value)))
    return element

def get_dropdown(driver, dropdown_name):
    dropdown = wait_and_click(driver, By.NAME, dropdown_name)
    dropdown_list = [*map(lambda x:x.get_attribute('text'), Select(dropdown).options)]
    return dropdown_list

def is_file_empty(path):
    return os.path.getsize(path) == 0

def snapshot_files(path):
    return {f.name for f in Path(path).glob('*')}

def wait_for_new_download(
    download_dir,
    before_snapshot,
    timeout = 30,
    stable_secs = 1.0
):
    """
    Waits until a new file appears and stops changing size.
    Returns the Path to the downloaded file.
    
    """

    download_dir = Path(download_dir)
    start = time.time()
    last_sizes = {}

    while time.time() - start < timeout:
        current_files = {f.name for f in download_dir.glob('*')}
        new_files = current_files - before_snapshot

        # Ignore temporary files
        new_files = {
            f for f in new_files
            if not f.endswith('.crdownload')
        }

        if new_files:
            file_path = download_dir / next(iter(new_files))

            size = file_path.stat().st_size
            prev_size = last_sizes.get(file_path.name)

            if prev_size == size:
                time.sleep(stable_secs)
                if file_path.stat().st_size == size:
                    return file_path
                
            last_sizes[file_path.name] = size

        time.sleep(0.2)

    raise TimeoutError('Download did not appeared or stabilized')

# ---- Internal helpers ------------------------------------------

def _save_empty_file(file_name:str, output_dir: Path, file_key:str) -> None:
    """
    Saves a zero-row Excel xls file with correct headers to signal
    that dividends were queried for run_date but none were found.
    Distinguishes "not queried" from "queried, none found".
    
    """
    file_key_cols = {
        'dividendos':[
            'FECHA VECTOR', 'C&Oacute;DIGO SBS', 'ISIN', 'NEM&Oacute;NICO',
            'EMISOR', 'MONEDA', 'FACTOR DE AJUSTE', 'TIPO DE ENTREGA DE DERECHO'
        ],
        'alternativos':[
            'C&Oacute;DIGO SBS', 'EMISOR', 'DESCRIPCI&Oacute;N', 'FECHA ACTUALIZACI&Oacute;N',
            'NOMBRE DOCUMENTO RECIBIDO', 'PRECIO DE ACTUALIZACI&Oacute;N'
        ],
        'fondos_inversion':[
            'C&Oacute;DIGO SBS', 'EMISOR', 'DESCRIPCI&Oacute;N', 'FECHA ACTUALIZACI&Oacute;N',
            'NOMBRE DOCUMENTO RECIBIDO', 'PRECIO DE ACTUALIZACI&Oacute;N'
        ]
    }

    if file_key not in file_key_cols.keys():
        logger.warning(f'File type key {file_key} not in valid keys. Skipping.')
        return None

    empty_df = pd.DataFrame(columns=file_key_cols[file_key])

    empty_df.to_csv(output_dir / file_name, index=False, encoding = 'latin-1', sep = '\t') #encoding = 'latin-1', sep = '\t'
    logger.info(f'Saved empty {file_key} sentinel: {output_dir / file_name}')



def _resolve_file_types(
    file_types: Optional[list[str]], 
    sbs_files: Optional[list[dict]]
) -> dict:
    """
    Returns the subset of SBS_FILES matching file_tpyes.
    Returns all SBS if file_types is None.
    Logs a warning for any unrecognised file type name.
    
    :param file_types: Valid str name of file vector type
    :type file_types: Optional[list[str]]
    """
    registry = sbs_files if sbs_files is not None else SBS_FILES

    if file_types is None:
        return registry
    
    known_names = set(registry.keys()) #{f for f in SBS_FILES.keys()}
    unknown = [ft for ft in file_types if ft not in known_names]
    if unknown:
        logger.warning(
            f'Unrecognised file types (will be ignored): {unknown}. '
            f'Known types: {sorted(known_names)}'
        )

    resolved = {k:v for k, v in registry.items() if k in file_types}
    if not resolved:
        logger.warning('No valid file types matched. Nothing to download.')
    return resolved

def _get_eligible_dates(
    driver,
    start_date: date,
    end_date: date
) -> list[date]:
    """
    Reads the date select element from the portal within the active session.
    Returns dates available in the portal within [start_date, end_date].
    
    """
    try:
        # Navigate to a page that has the date selector
        driver.get(f"{SBS_BASE_URL}{SBS_FILES['vector_completo']['url_landing']}")
        
        option_values = get_dropdown(driver, SBS_FILES['vector_completo']['fecha_dropdown_name'])
        
        eligible = []
        for val in option_values:
            try:
                # Adjust date parsing if portal uses DD/MM/YYYY or other format
                #d = date.fromisoformat(val)
                d = datetime.strptime(val, '%d/%m/%Y').date()
                if start_date <= d <= end_date:
                    eligible.append(d)
            except ValueError:
                continue

        logger.info(
            f'Portal has {len(eligible)} dates in range '
            f'{start_date} to {end_date}'
        )
        return sorted(eligible)
    
    except Exception as e:
        logger.error(
            f'Failed to read eligible dates from portal: {e}',
            exc_info=True
        )
        return []

    except:
        pass

def _diff_against_raw(
    eligible_dates: list[date],
    files_to_download: dict,
    raw_dir: Optional[Path] = None
) -> list[date]:
    """
    Returns dates from eligible_dates where at least one expected
    file is missing from data/raw/.
    A date is considered complete only if ALL expected files exist.

    :param eligible_dates: Date list as returned as _get_eligible_dates
    :type eligible_dates: list[date]
    :param files_to_download: Dict of dictionaries from picked SBS_FILES
    :type files_to_download: dict
    """
    download_dir = _resolve_raw_dir(raw_dir)

    missing = []
    for d in eligible_dates:
        date_prefix = d.strftime('%Y%m%d')
        all_present = all(
            (download_dir / f['folder'] / (date_prefix + f.get('postfix','') + '.xls')).exists()
            for f in files_to_download.values()
        )
        if not all_present:
            missing.append(d)
    return missing

def all_files_present(
    run_date: date,
    file_types: Optional[list[str]] = None,
    raw_dir: Optional[Path] = None,
    sbs_files: Optional[list[dict]] = None
) -> bool:
    """
    Returns True if all expected SBS files are already present
    in data/raw/ for run_date.
    Used as pre-acquisition check to skip unnecessary browser
    sessions when file were already downloaded.
    
    """
    files_to_check = _resolve_file_types(file_types, sbs_files)
    date_prefix = run_date.strftime('%Y%m%d')
    return all(
        (path := find_latest_file(f['folder'], run_date, raw_dir)) is not None
        and path.stem[:8] == date_prefix
        for f in files_to_check.values()
    )

def _resolve_raw_dir(raw_dir: Optional[Path] = None) -> Path:
    """
    Returns the raw dir to use, falling back to module-level default.
    """
    return raw_dir if raw_dir is not None else VP_SBS_DIR

def _resolve_sbs_files(sbs_files: Optional[list[dict]] = None) -> list[dict]:
    return sbs_files if sbs_files is not None else SBS_FILES

def _get_xls_name():
    return
# if __name__ == "__main__":
#     setup_logging('aquire_range')
#     acquire_range(
#         start_date=date(2015,1,1),
#         end_date=date(2016,1,1),#date.today()-timedelta(days=1),
#         file_types=['tipo_cambio', 'dividendos']
#     )
