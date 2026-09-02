# src/scrapers/spp.py
# ---------------------------------------------------------------
# Acquisition for the SPP valor cuota feed (www.sbs.gob.pe).
#
# The SBS main site sits behind the Imperva/Incapsula WAF: requests,
# curl and headless browsers all receive a block page. The only path
# through is REAL Chrome, visible, with a persistent profile that
# keeps the WAF cookie between runs - which is why this scraper uses
# Playwright (channel='chrome', headless=False) instead of the
# Selenium+chromedriver stack the other scrapers use, and why the
# scheduled task that drives it must run in an interactive session.
#
# Acquisition only: HTML/bytes in, files under data/raw/spp/ as a
# trail. Parsing lives in the pipeline's extract.py.
# ---------------------------------------------------------------

import logging
import time
from datetime import date
from pathlib import Path

import requests

from src.shared.paths import DATA_DIR, RAW_DIR

logger = logging.getLogger(__name__)

URL_DIARIO = "https://www.sbs.gob.pe/app/spp/variablesSPP_net/PagSS/variables_spp.aspx"
URL_INDICE_HISTORICO = ("https://www.sbs.gob.pe/app/stats/"
                        "EstadisticaSistemaFinancieroResultadosHist.asp?c=FP-130706&Y=0")
TEXTO_ENLACE_HISTORICO = "Valores cuota (desde"

SELECTOR_TABLA_DIARIA = "table.APLI_tabla2"

# Persistent Chrome profile: holds the Imperva cookie between runs.
PROFILE_DIR = DATA_DIR / "browser_profile_spp"
SPP_RAW_DIR = RAW_DIR / "spp"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def fetch_html(url: str, wait_selector: str | None = None,
               retries: int = 3) -> str:
    """
    Downloads a page from www.sbs.gob.pe through the WAF.

    Playwright is imported inside the function so machines without it
    (office installs, CI) can still import the module; only actually
    scraping requires the dependency.
    """
    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    last_error = None
    for attempt in range(1, retries + 1):
        p = ctx = None
        try:
            p = sync_playwright().start()
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR), channel="chrome", headless=False,
                locale="es-PE", timezone_id="America/Lima",
                viewport={"width": 1440, "height": 1000},
                args=["--disable-blink-features=AutomationControlled"])
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=45_000)
            else:
                page.wait_for_timeout(4_000)
            html = page.content()
            if "_Incapsula_Resource" in html:
                raise RuntimeError("El WAF bloqueo la peticion.")
            return html
        except Exception as exc:
            last_error = exc
            logger.warning(f"spp fetch attempt {attempt}/{retries} failed: "
                           f"{str(exc).splitlines()[0][:120]}")
            if attempt < retries:
                time.sleep(4 * attempt)
        finally:
            for closer in (getattr(ctx, "close", None), getattr(p, "stop", None)):
                if closer:
                    try:
                        closer()
                    except Exception:
                        pass
    raise RuntimeError(f"No se pudo abrir {url}: {last_error}")


def fetch_daily_html(run_date: date | None = None) -> str:
    """
    The SPP variables page (last 7 business days, three metrics per
    AFP x fund). Saves a raw copy under data/raw/spp/ as the trail.
    """
    logger.info("Abriendo la pagina diaria de variables SPP...")
    html = fetch_html(URL_DIARIO, wait_selector=SELECTOR_TABLA_DIARIA)
    stamp = (run_date or date.today()).strftime("%Y%m%d")
    SPP_RAW_DIR.mkdir(parents=True, exist_ok=True)
    (SPP_RAW_DIR / f"variables_spp_{stamp}.html").write_text(html, encoding="utf-8")
    return html


def download_historic_xls() -> Path:
    """
    Resolves and downloads the SBS monthly historical XLS (valor cuota
    since Aug 1993). Only the index page needs the WAF-piercing Chrome;
    the file link itself downloads over plain requests.
    """
    from bs4 import BeautifulSoup

    logger.info("Resolviendo el enlace del XLS historico...")
    html = fetch_html(URL_INDICE_HISTORICO)
    url = None
    for a in BeautifulSoup(html, "lxml").find_all("a"):
        if " ".join(a.get_text(" ").split()).lower().startswith(
                TEXTO_ENLACE_HISTORICO.lower()):
            url = a.get("href")
            break
    if not url:
        raise RuntimeError("No se encontro el enlace del XLS historico.")

    logger.info(f"Descargando {url.rsplit('/', 1)[-1]}")
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=180)
    r.raise_for_status()
    SPP_RAW_DIR.mkdir(parents=True, exist_ok=True)
    destino = SPP_RAW_DIR / Path(url).name
    destino.write_bytes(r.content)
    logger.info(f"Descargados {len(r.content):,} bytes -> {destino}")
    return destino
