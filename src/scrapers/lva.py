# src/scrapers/lva.py
# ---------------------------------------------------------------
# LVA portal scraper (Selenium): logs in and downloads LVA index files
# into the raw data tree.

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import pandas as pd
import time
from datetime import date, timedelta

from pathlib import Path
import logging

from src.configs.machine_config import chromedriver_path
from src.shared.env import required
from src.shared.paths import RAW_DIR
from src.shared.logging import setup_logging

logger = logging.getLogger(__name__)

def create_driver() -> webdriver.Chrome:
    # Ruta al driver
    service = Service(chromedriver_path(), log_output="NUL")

    # Opciones del navegador
    options = Options()
    
    prefs = {
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

def snapshot_files(path: str) -> set:
    return {f.name for f in Path(path).glob('*')}

def login(driver, timeout_seconds: int = 10) -> None:
    wait = WebDriverWait(driver, timeout_seconds)

    # Credentials come from the environment (.env at the repo root),
    # never from source. See ROTATION.md.
    username_box = wait.until(EC.element_to_be_clickable((By.ID, 'user')))
    username_box.clear()
    username_box.send_keys(required('LVA_USER'))

    password_box = wait.until(EC.element_to_be_clickable((By.ID, 'password')))
    password_box.clear()
    password_box.send_keys(required('LVA_PASSWORD'))

    # Ingresar
    ingresar_button = wait.until(EC.element_to_be_clickable((By.ID, 'btnSubmit')))
    ingresar_button.click()

def date_to_set(run_date:date) -> set:
    MONTH_PREFIX_MAP = {
        1:'Ene', 2:'Feb', 3:'Mar',
        4:'Abr', 5:'May', 6:'Jun',
        7:'Jul', 8:'Ago', 9:'Sep',
        10:'Oct', 11:'Nov', 12:'Dic'
    }

    date_set = {
        'year':run_date.year, 
        'month':MONTH_PREFIX_MAP[run_date.month],
        'day':run_date.day
    }

    return date_set

def select_date(
        driver,
        date_item, 
        run_date:date,
        timeout_seconds: int = 10
    ) -> bool:
    """
    Select date for LVA indices portal. 
    Returns True if date is reachable (aka has data) and False otherwise
    
    """
    try:
        date_set = date_to_set(run_date)
    except Exception as e:
        logger.error(f'Invalid date: {e}')
        raise ValueError
    
    year, month, day = date_set.values()
    
    wait = WebDriverWait(driver, timeout_seconds)

    # Open calendar
    date_item.click()

    # Open year selector
    year_selector = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, '//span[contains(@class, "dhtmlxcalendar_month_label_year")]')
        ))
    year_selector.click()

    # Choose year
    year_option = wait.until(
            EC.element_to_be_clickable((
                By.XPATH,
                f'//li[contains(@class, "dhtmlxcalendar_selector_cell") and normalize-space(text())="{year}"]'
            ))
        )
    year_option.click()
    # TODO: extend for sliding left/right if year is unreachable

    # Open month selector
    month_selector = wait.until(
        EC.visibility_of_element_located(
            (By.XPATH, '//span[contains(@class, "dhtmlxcalendar_month_label_month")]')
        ))
    month_selector.click()

    # Choose month
    month_option = wait.until(
            EC.element_to_be_clickable((
                By.XPATH,
                f'//li[contains(@class, "dhtmlxcalendar_selector_cell") and normalize-space(text())="{month}"]'
            ))
        )
    month_option.click()

    # Choose day
    day_option = wait.until(
            EC.element_to_be_clickable((
                By.XPATH,
                f'//li[contains(@class, "dhtmlxcalendar_cell_month")]'
                f'[.//div[contains(@class, "dhtmlxcalendar_label") and normalize-space(text())="{day}"]]'
            ))
        )
    
    day_option.click()

    day_op_class = day_option.get_attribute('class')
    if day_op_class == 'dhtmlxcalendar_cell dhtmlxcalendar_cell_month_dis':
        logger.warning('Date without data, skipping')
        return False
    elif day_op_class == 'dhtmlxcalendar_cell dhtmlxcalendar_cell_month_date':
        #logger.info('Date reached')
        return True

def wait_loading(driver, timeout_seconds:int = 10) -> None:
    wait = WebDriverWait(driver, timeout_seconds)
    
    wait.until(EC.all_of(
        EC.invisibility_of_element_located((
            By.XPATH, '//img[@alt="Loading..."]'
        )),
        EC.invisibility_of_element_located((
            By.XPATH, '//div[@id="loading" and contains(@class, "loading-visible")]'
        ))
    ))

def wait_rows(driver, timeout_seconds:int = 10) -> None:
    
    objbox_xpath = '(//div[contains(@class,"objbox")])[1]'
    rows_xpath   = objbox_xpath + '//tr'

    wait = WebDriverWait(driver, timeout_seconds)
    wait.until(
        EC.visibility_of_element_located((
            By.XPATH, objbox_xpath
        ))
    )

    wait.until(lambda d: len(d.find_elements(By.XPATH, rows_xpath)) > 1)

def get_indices_df(driver, run_date:date) -> pd.DataFrame:

    # Get html
    html = driver.page_source

    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')

    # Read the headers from the first table in the html
    header = []
    for tr in tables[0].find_all('tr'):
        cells = [td.get_text(strip=True) for td in tr.find_all(['td','th'])]
        header.append(cells)
    header = header[1]

    # Read the rest of the rows from the second table in the html
    rows = []
    for tr in tables[1].find_all('tr'):
        cells = [td.get_text(strip=True) for td in tr.find_all(['td','th'])]
        rows.append(cells)

    # Dataframe
    lva_indices_df = pd.DataFrame(rows[1:], columns = header)

    # Add date to table
    lva_indices_df['Fecha'] = pd.to_datetime(run_date, dayfirst=True).date()

    return lva_indices_df

def _get_csv_name(run_date:date) -> str:
    return 'Indices_RF_PE_' + run_date.strftime('%Y%m%d')

def save_df(df:pd.DataFrame, run_date:date) -> None:
    df.to_csv(
        RAW_DIR / 'lva' / 'diarios' / (_get_csv_name(run_date) + '.csv'),
        index=False, 
        encoding='utf-8-sig')

def download_day(
        run_date:date,
        timeout_seconds: int = 10
    ) -> bool:
    
    logger.info(f'Downloading LVA Indices for {run_date}')

    driver = create_driver()
    driver.get('https://peru.lvaindices.com/login/Default.asp?origen=INDICEDIARIO')

    login(driver)
    wait_loading(driver)

    try:
        date_item = WebDriverWait(driver, timeout_seconds).until(EC.element_to_be_clickable((By.ID, 'fecha')))
        date_reached = select_date(driver, date_item=date_item, run_date=run_date)
        
        if not date_reached:
            logger.warning(f'No data for {run_date}')
            return False
        
        wait_loading(driver)
        wait_rows(driver)
        
        df = get_indices_df(driver, run_date)
        if df.empty:
            logger.warning('HTML parsing returned no rows')
        save_df(df, run_date)
        logger.info(f'Indices LVA downloaded for {run_date}')
        return True
    except Exception as e:
        logger.error(f'Error downloading {run_date}: {e}')
        return False
    finally:
        driver.close()

def download_range(
        start_date:date,
        end_date:date,
        timeout_seconds: int = 10
    ) -> dict:
    
    # Date range
    if start_date < date(2007,8,1):
        logger.warning('No data prior 2007-08-01, setting it as start date')
        start_date = date(2007,8,1)

    eligible_dates = pd.bdate_range(start_date, end_date).date
    
    logger.info(f'Downloading LVA Indices from {start_date} to {end_date}')

    # diff against filesystem
    dates_to_download = _diff_against_raw(eligible_dates = eligible_dates)

    if not dates_to_download:
        logger.info('All eligible dates already in raw/. Nothing to download.')
        driver.close()
        return {'successed':[], 'failed':[], 'skipped':eligible_dates}
    
    logger.info(
        f'{len(dates_to_download)} dates missing from raw/. '
        f'{len(eligible_dates) - len(dates_to_download)}'
    )
    skipped = [d for d in eligible_dates if d not in dates_to_download]

    driver = create_driver()
    driver.get('https://peru.lvaindices.com/login/Default.asp?origen=INDICEDIARIO')

    login(driver)
    wait_loading(driver)

    day_results = {}
    succeeded = []
    failed = []
    skipped = []
    
    for run_date in dates_to_download:
        try:
            if Path(RAW_DIR / 'lva' / 'diarios' / (_get_csv_name(run_date) + '.csv')).exists():
                day_results[run_date] = 'skipped'
                continue

            date_item = WebDriverWait(driver, timeout_seconds).until(EC.element_to_be_clickable((By.ID, 'fecha')))
            date_reached = select_date(driver, date_item=date_item, run_date=run_date)
            
            if not date_reached:
                logger.warning(f'No data for {run_date}')
                day_results[run_date] = 'failed'
                continue
            
            wait_loading(driver)
            wait_rows(driver)
            
            df = get_indices_df(driver, run_date)
            if df.empty:
                logger.warning('HTML parsing returned no rows')
            save_df(df, run_date)
            day_results[run_date] = 'ok'

            logger.info(f'Indices LVA downloaded for {run_date}')
        except Exception as e:
            logger.error(f'Error downloading {run_date}: {e}')
            day_results[run_date] = 'failed'
    
    driver.close()

    for run_date, status in day_results.items():
        if status == 'ok':
            succeeded.append(run_date)
        elif status == 'skipped':
            skipped.append(run_date)
        else:
            failed.append(run_date)

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

def _diff_against_raw(
    eligible_dates: list[date]
) -> list[date]:
    """
    Returns dates from eligible_dates where expected file is missing from data/raw/.

    :param eligible_dates: Date list as returned as _get_eligible_dates
    :type eligible_dates: list[date]
    :param files_to_download: Dict of dictionaries from picked SBS_FILES
    :type files_to_download: dict
    """
    missing = []
    for d in eligible_dates:
        file_name = _get_csv_name(d)
        present = (RAW_DIR / 'lva' / 'diarios' / (file_name + '.csv')).exists()
        if not present:
            missing.append(d)
    return missing

if __name__ == "__main__":
    # setup_logging('lva_indices_day')
    # get_date = date(2026,4,30)
    # download_day(get_date)
    
    setup_logging('lva_indices_range')
    download_range(
        start_date=date(2026,1,1),
        end_date=date.today() - timedelta(days=1)
    )

