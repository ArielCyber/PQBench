import logging
import os
import socket
import struct
import sys
import time
import winreg
from pathlib import Path
from logging.handlers import RotatingFileHandler

import requests
from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.common import WebDriverException
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.firefox import GeckoDriverManager
import os, sys, time
import certifi

# ---------- TLS certs ----------
os.environ.pop("REQUESTS_CA_BUNDLE", None)
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
os.environ["SSL_CERT_FILE"] = certifi.where()

# ========== NEW: one-time geckodriver resolver (cache then offline) ==========
WDM_CACHE_DIR = Path.home() / ".wdm"
WDM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_GECKO_TXT = WDM_CACHE_DIR / "geckodriver_path.txt"
_GECKO_VERSION = "v0.36.0"  # pin; bump when you decide to upgrade


def _read_saved_gecko_path() -> str | None:
    """Return a previously saved geckodriver path (or from PATH) if valid."""
    # Env override (lets you hot-patch without changing code)
    p = os.environ.get("GECKODRIVER_PATH")
    if p and Path(p).is_file():
        return p
    # Saved path file
    if _GECKO_TXT.is_file():
        saved = _GECKO_TXT.read_text(encoding="utf-8").strip()
        if saved and Path(saved).is_file():
            return saved
    # Last resort: try PATH
    import shutil
    p = shutil.which("geckodriver")
    return p

def _save_gecko_path(p: str) -> None:
    _GECKO_TXT.parent.mkdir(parents=True, exist_ok=True)
    _GECKO_TXT.write_text(p, encoding="utf-8")

def ensure_geckodriver_path() -> str:
    """
    First run: use webdriver-manager to download geckodriver into WDM_CACHE_DIR,
    save its absolute path, then force offline cache for future runs.
    Later runs: reuse the saved path and keep webdriver-manager offline.
    """
    # If we already have a path, force offline and return it
    existing = _read_saved_gecko_path()
    if existing:
        logging.debug(f"GeckoDriver exists: {existing}")
        os.environ.setdefault("WDM_LOCAL", "1")  # stay offline (no GitHub calls)
        return existing

    logging.debug("Trying to install GeckoDriver")
    # old/new API compatibility
    try:
        # new-ish API (some builds accept "version=")
        driver_path = GeckoDriverManager(version=_GECKO_VERSION, path=str(WDM_CACHE_DIR)).install()
    except TypeError:
        logging.debug("TypeError in GeckoDriver path")
        # newer API that renamed to driver_version (keep as fallback just in case)
        try:
            driver_path = GeckoDriverManager(version=_GECKO_VERSION).install()
        except TypeError:
            logging.debug("TypeError in GeckoDriver version")
            driver_path = GeckoDriverManager(version=_GECKO_VERSION).install()


    logging.debug(f"Installed GeckoDriver at path: {driver_path}")
    _save_gecko_path(driver_path)
    os.environ["WDM_LOCAL"] = "1"  # subsequent runs use cache only
    return driver_path
# =============================== end NEW =====================================


def _wait_https_ready(url="https://www.google.com", timeout_s=120):
    """Block until outbound HTTPS works; avoids early TLS errors."""
    t0 = time.time()
    delay = 2
    while time.time() - t0 < timeout_s:
        try:
            requests.get(url, timeout=5, verify=certifi.where())
            logging.debug("Request succeeded")
            return True
        except Exception:
            logging.debug(f"Request timed out: {url}")
            time.sleep(delay)
            delay = min(delay * 1.5, 10)
    return False


app = Flask(__name__)

log_path = os.getenv("PY_LOG_FILE", r"C:\OEM\processor.log")
Path(log_path).parent.mkdir(parents=True, exist_ok=True)

handlers = [
    logging.StreamHandler(sys.stdout),
    RotatingFileHandler(log_path, maxBytes=10_000_000, backupCount=5, encoding="utf-8")
]

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d in %(funcName)s() - %(message)s",
    handlers=handlers,
    force=True,
)


def _default_gateway_ip() -> str | None:
    try:
        with open("/proc/net/route") as f:
            next(f)  # header
            for line in f:
                parts = line.split()
                if parts[1] == '00000000':  # default route
                    gw_hex = parts[2]
                    gw = socket.inet_ntoa(struct.pack("<L", int(gw_hex, 16)))
                    return gw
    except Exception:
        return None


def resolve_switcher_url() -> str:
    env_url = os.getenv("SWITCHER_URL")
    if env_url:
        return env_url
    try:
        requests.get("http://host.docker.internal:8080/health", timeout=1)
        return "http://host.docker.internal:8080"
    except Exception:
        pass
    gw = _default_gateway_ip()
    if gw:
        return f"http://{gw}:8080"
    return "http://host.docker.internal:8080"


SWITCHER_URL = resolve_switcher_url()
logging.debug(f"SNIFFER_URL is {SWITCHER_URL}")


@app.get("/health")
def health():
    return "ok", 200


def open_browser(browser: str, algo: int):
    _wait_https_ready()
    try:
        if browser.lower() == 'chrome':
            return open_chrome(algo)
        else:
            return open_firefox(algo)
    except WebDriverException as e:
        raise e


def open_firefox(algo):
    """
    Launch a Selenium WebDriver for Firefox with a given algorithm.
    Uses one-time geckodriver install then reuses cached path.
    """
    logging.debug("Trying to open Firefox")

    firefox_opts = webdriver.FirefoxOptions()
    firefox_opts.add_argument("-headless")

    if algo == 0:
        firefox_opts.set_preference('network.http.http3.enable_kyber', False)
        firefox_opts.set_preference('security.tls.enable_kyber', False)
        logging.debug("Set non PQC preferences")
    if algo == 1 or algo == 2:
        firefox_opts.set_preference("security.tls.enable_kyber", True)
        firefox_opts.set_preference("network.http.http3.enabled", True)
        firefox_opts.set_preference("network.http.http3.enable_kyber", True)
        logging.debug("Set PQC on")

    try:
        # ========== CHANGED: one-time install then reuse ==========
        gecko_path = ensure_geckodriver_path()
        logging.debug(f"Using geckodriver at: {gecko_path}")
        return webdriver.Firefox(service=FirefoxService(gecko_path), options=firefox_opts)
    except WebDriverException as e:
        logging.critical(e)
        raise BrowserLaunchError("Failed to open Firefox: is Firefox installed and the driver up to date?") from e


def open_chrome(algo):
    chrome_opts = webdriver.ChromeOptions()
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--headless=new")
    chrome_opts.add_argument("--disable-gpu")
    chrome_opts.add_argument("--disable-dev-shm-usage")
    chrome_opts.add_argument("--remote-debugging-port=0")

    prefs = {"browser": {"enabled_labs_experiments": []}}

    if algo == 0:
        prefs["browser"]["enabled_labs_experiments"] = ["enable-tls13-kyber@2"]
    elif algo == 1:
        prefs["browser"]["enabled_labs_experiments"] = ["enable-tls13-kyber@1"]
    elif algo == 2:  # ML-KEM
        prefs["browser"]["enabled_labs_experiments"] = [
            "enable-tls13-kyber@2",
            "use-ml-kem@1",
        ]

    chrome_opts.add_experimental_option("localState", prefs)

    try:
        algo_mode = os.getenv("MODE")
        if algo_mode == "KYBER":
            chromedriver_path = ChromeDriverManager(driver_version="128.0.6613.138").install()
        elif algo_mode == "MLKEM":
            chromedriver_path = ChromeDriverManager(driver_version="139.0.7258.155").install()
        else:
            raise RuntimeError("MODE env variable must be 'KYBER' or 'MLKEM'")
        service = ChromeService(executable_path=chromedriver_path)
        return webdriver.Chrome(options=chrome_opts, service=service)
    except WebDriverException as e:
        logging.critical(e)
        raise BrowserLaunchError("Failed to open Chrome: is Chrome installed and the driver up to date?") from e


def process_session(browser: str, algo: int, amount: int, domain: str):
    for i in range(amount):
        driver = open_browser(browser, algo)
        logging.debug(f"The driver opened: {driver}")
        driver.get(f'https://{domain}')
        logging.debug(f"The driver opened the given domain")
        try:
            logging.debug(f"Waiting for the web driver")
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete")
            time.sleep(3)
        finally:
            driver.quit()
    return {"status": "done"}


def _measure_one_session(browser: str, algo: int, domain: str) -> float:
    t0 = time.monotonic()
    d = open_browser(browser, algo)
    try:
        d.get(f"https://{domain}")
        WebDriverWait(d, 10).until(lambda drv: drv.execute_script("return document.readyState") == "complete")
        time.sleep(3)
    finally:
        d.quit()
    logging.debug(f"Session time: {time.monotonic() - t0}")
    return time.monotonic() - t0


@app.route('/')
def root():
    algo_mode = os.getenv("MODE")
    logging.debug(f"ALGO MODE is {algo_mode}")
    if algo_mode == "KYBER":
        logging.debug("Returning kyber html")
        return app.send_static_file('kyber_page.html')
    elif algo_mode == "MLKEM":
        logging.debug("Returning mlkem html")
        return app.send_static_file('mlkem_page.html')
    return None


@app.route('/execute', methods=['POST'])
def config_handler():
    logging.info("Starting PQBench session...")
    data = request.get_json() or request.form
    try:
        browser = data['browser']
        logging.debug(f"Browser: {browser}")
        algo = int(data['algorithm'])
        logging.debug(f"Algo: {algo}")
        amount = int(data['sessions'])
        logging.debug(f"Amount: {amount}")
        domain = data.get('domain', 'pq.cloudflareresearch.com')
    except (KeyError, ValueError) as e:
        logging.error(f"Bad request: {e}")
        return jsonify({'Error': f'Bad request: {e}'}), 400

    if amount <= 0:
        logging.error("Sessions count must be greater than 0.")
        return jsonify('Error: session count must be a positive number')

    try:
        response = process_session(browser, algo, amount, domain)
        return jsonify(response), 200
    except BrowserLaunchError as e:
        result = jsonify({'Error': str(e)}), 500
        logging.error(f"{e}")
        return result
    except Exception as e:
        app.logger.exception(e)
        logging.error(f"{e}")
        return jsonify({'Error': f'Unexpected server error: {e}'}), 500


class BrowserLaunchError(RuntimeError):
    pass


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
