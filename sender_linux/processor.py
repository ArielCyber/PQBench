import logging
import os
import socket
import struct
import sys
import time
import requests
from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.common import WebDriverException
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.firefox import GeckoDriverManager

app = Flask(__name__)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)])

default_domain = "pq.cloudflareresearch.com"


def _default_gateway_ip() -> str | None:
    """
    Discover the default gateway IP address inside a Linux container.

    This function parses `/proc/net/route` to find the kernel's routing
    table. Each line corresponds to a route entry:
        - Column 1: interface name
        - Column 2: destination (hex)
        - Column 3: gateway (hex)
    If the destination is `00000000`, it represents the **default route**
    (i.e., "all traffic not otherwise specified").

    The gateway address is stored in little-endian hexadecimal form.
    We convert it into a 32-bit integer, then into a human-readable IPv4
    string using `socket.inet_ntoa`.

    Returns
    -------
    str or None
        The default gateway IPv4 address as a string (e.g. "172.17.0.1"),
        or None if it cannot be determined.
    """
    # parse /proc/net/route (little endian hex)
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


def resolve_sniffer_url() -> str:
    """
    Resolve the URL of the sniffer service, with multiple fallback strategies.

    Priority order:
    1. **Environment variable** (`SNIFFER_URL`): If set, always use this value.
    2. **Docker Desktop special DNS name**: Try contacting
       `http://host.docker.internal:8080/health`. This works when the sniffer
       runs on the Windows/Mac host and is reachable via Docker Desktop's
       built-in host alias.
    3. **Linux container gateway fallback**: If the sniffer is running in
       `network_mode: host` on the Docker Desktop VM OR Linux host, the correct way to reach
       it is via the default gateway of the container’s bridge network
       (determined by `_default_gateway_ip()`).
    4. **Final fallback**: Default again to
       `"http://host.docker.internal:8080"` if all else fails.

    Returns
    -------
    str
        The base URL of the sniffer service to contact.
    """
    # env override
    env_url = os.getenv("SNIFFER_URL")
    if env_url:
        return env_url
    # try host.docker.internal first (works on Desktop if service is on the Windows host)
    try:
        requests.get("http://host.docker.internal:8080/health", timeout=1)
        return "http://host.docker.internal:8080"
    except Exception:
        pass
    # fall back to Docker Desktop VM gateway
    gw = _default_gateway_ip()
    if gw:
        return f"http://{gw}:8080"
    # final fallback
    return "http://host.docker.internal:8080"


SNIFFER_URL = resolve_sniffer_url()
logging.debug(f"SNIFFER_URL is {SNIFFER_URL}")


@app.route('/')
def root():
    """
    Serve the main static HTML page.

    Returns
    -------
    Response
        The contents of 'mlkem_page.html' from the static folder.
    """
    algo_mode = os.getenv("MODE")
    logging.debug(f"ALGO MODE is {algo_mode}")
    if algo_mode == "KYBER":
        logging.debug("Returning kyber html")
        return app.send_static_file('kyber_page.html')
    elif algo_mode == "MLKEM":
        logging.debug("Returning mlkem html")
        return app.send_static_file('mlkem_page.html')
    # return app.send_static_file('kyber_page.html')


def open_browser(browser: str, algo: int):
    """
    The decision-making for which browser should be opened

    Parameters
    ----------
    browser : str
        'chrome' or 'firefox'.
    algo : int
        0 for non PQC
        1 for Kyber
        2 for MLKEM

    Returns
    -------
    WebDriver
        An instance of Chrome or Firefox WebDriver.

    Raises
    ------
    BrowserLaunchError
        If the driver fails to start or browser is not installed.
    """

    try:
        if browser.lower() == 'chrome':
            return open_chrome(algo)
        else:
            return open_firefox(algo)
    except WebDriverException as e:
        raise e


def open_firefox(algo):
    """
    Launch a Selenium WebDriver for Firefox with a given Algo.
    """
    logging.debug("Trying to open Firefox")

    firefox_opts = webdriver.FirefoxOptions()

    # Headless mode
    firefox_opts.add_argument("-headless")

    if algo == 0:
        firefox_opts.set_preference('network.http.http3.enable_kyber', False)
        firefox_opts.set_preference('security.tls.enable_kyber', False)
        logging.debug("Set non PQC preferences")
    if algo == 1 or algo == 2:  # Enable Kyber or MLKEM (Same flags)
        firefox_opts.set_preference("security.tls.enable_kyber", True)
        firefox_opts.set_preference("network.http.http3.enabled", True)
        firefox_opts.set_preference("network.http.http3.enable_kyber", True)
        logging.debug("Set PQC on")

    try:
        gecko_path = GeckoDriverManager().install()
        logging.debug("Installed GeckoDriverManager successfully!")
        return webdriver.Firefox(service=FirefoxService(gecko_path), options=firefox_opts, )
    except WebDriverException as e:
        logging.critical(e)
        raise BrowserLaunchError("Failed to open Firefox: is Firefox installed and the driver up to date?") from e


def open_chrome(algo):
    chrome_opts = webdriver.ChromeOptions()

    # Headless Chrome
    chrome_opts.add_argument("--no-sandbox")  # containers often need this
    chrome_opts.add_argument("--headless=new")
    chrome_opts.add_argument("--disable-gpu")  # Windows workaround
    chrome_opts.add_argument("--disable-dev-shm-usage")
    chrome_opts.add_argument("--remote-debugging-port=0")  # avoids DevTools port collision

    prefs = {"browser": {"enabled_labs_experiments": []}}

    # ----- Chrome PQC experiments (via Local State "enabled_labs_experiments") -----
    if algo == 0:
        prefs["browser"]["enabled_labs_experiments"] = [
            "enable-tls13-kyber@2",
            "use-ml-kem@2"]

    elif algo == 1:
        prefs["browser"]["enabled_labs_experiments"] = [
            "use-ml-kem@2"]
    elif algo == 2:  # ML-KEM
        prefs["browser"]["enabled_labs_experiments"] = [
            "enable-tls13-kyber@2",  # Disabled
            "use-ml-kem@1",  # Enabled
        ]

    chrome_opts.add_experimental_option("localState", prefs)

    try:
        chromedriver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/local/bin/chromedriver")
        service = ChromeService(executable_path=chromedriver_path)
        return webdriver.Chrome(options=chrome_opts, service=service)
    except WebDriverException as e:
        logging.critical(e)
        raise BrowserLaunchError("Failed to open Chrome: is Chrome installed and the driver up to date?") from e


def get_container_ip():
    return socket.gethostbyname(socket.gethostname())


def start_sniffer(os_name: str, browser: str, algo: int, domain: str,
                  duration: int = 30, iface: str = "pqbench0",
                  filter_mode: str = "domain", custom_bpf: str | None = None):
    target_ip = get_container_ip()
    logging.debug(f"TARGET_IP is {target_ip}")
    payload = {
        "os": os_name,
        "browser": browser,
        "algo": algo,  # 1=Non-PQC, 2=Kyber, 3=MLKEM
        "container_ip": target_ip,  # this testapp's address on the bridge
        "duration_sec": duration,
        "iface": iface,
        "domain": domain,
        "split_streams": True,
        "filter_mode": filter_mode,
        "custom_bpf": custom_bpf
    }

    # tiny retry loop in case sniffer isn’t ready yet
    for attempt in range(10):
        try:
            r = requests.post(f"{SNIFFER_URL}/start", json=payload, timeout=5)
            r.raise_for_status()
            logging.info("Sniffer started: %s", r.json())
            return r.json()
        except Exception as e:
            logging.warning("Sniffer not ready yet (attempt %d): %s", attempt + 1, e)
            time.sleep(1)
    raise RuntimeError("Failed to reach sniffer API after retries")


def process_session(browser: str, algo: int, amount: int, domain: str):
    """
    Launch the browser to visit the domain.

    Parameters
    ----------
    browser : str
        'chrome' or 'firefox'.
    algo : int
        0 for non PQC
        1 for Kyber
        2 for MLKEM
    amount : int
        Number of sessions
    domain : str
        Target domain to visit.

    Returns
    -------
    dict
        JSON-serializable result with 'status'.
    """
    # ---- Trigger the sniffer ----
    try:
        sniffer_info = start_sniffer(
            os_name="linux",  # or detect dynamically
            browser=browser,
            algo=algo,
            duration=30,  # adjust capture window
            iface="pqbench0",
            domain=domain,
            filter_mode="domain"
        )
        logging.info(f"Sniffer started: {sniffer_info}")
    except Exception as e:
        logging.error(f"Could not start sniffer: {e}")
        # you can decide: return early, or continue without capture
        # return {"status": "sniffer unavailable"}

    for i in range(amount):
        driver = open_browser(browser, algo)
        logging.debug(f"The driver opened: {driver}")
        driver.get(f'https://{domain}')
        logging.debug(f"The driver opened the given domain")

        try:
            # Wait until document is fully ready (or a small dwell)
            logging.debug(f"Waiting for the web driver")
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete")
            time.sleep(3)
        finally:
            driver.quit()

    return {"status": "done"}


@app.route('/config', methods=['POST'])
def config_handler():
    """
    Flask endpoint to initiate a PQClass session based on client config.

    Parses JSON payload, validates inputs, runs `process_session`, and returns JSON result.

    Returns
    -------
    Response
        JSON response with either `status` and `directory` on success,
        or `error` message with appropriate HTTP status code.
    """
    logging.info("Starting PQBench session...")
    data = request.get_json() or request.form
    try:
        browser = data['browser']
        logging.debug(f"Browser: {browser}")
        algo = int(data['algorithm'])
        logging.debug(f"Algo: {algo}")
        amount = int(data['sessions'])
        logging.debug(f"Amount: {amount}")
        domain = data.get('domain', default_domain)
    except (KeyError, ValueError) as e:
        logging.error(f"Bad request: {e}")
        return jsonify({'Error': f'Bad request: {e}'}), 400

    if amount <= 0:
        logging.error("Sessions count must be greater than 0.")
        return jsonify('Error: session count must be a positive number')

    try:
        result = process_session(browser, algo, amount, domain)
        return jsonify(result), 200
    except BrowserLaunchError as e:
        # This is Browser startup error
        result = jsonify({'Error': str(e)}), 500
        logging.error(f"{e}")
        return result
    except Exception as e:
        # Catch anything else we didn’t anticipate
        app.logger.exception(e)
        logging.error(f"{e}")
        return jsonify({'Error': 'Unexpected server error'}), 500


class BrowserLaunchError(RuntimeError):
    """Raised when we fail to launch the requested browser."""
    pass


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
