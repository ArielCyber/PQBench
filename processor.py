import os
import socket
import shutil
import subprocess
import platform as platform_module
import sys

from scapy.all import rdpcap
from scapy.layers.inet import IP
from selenium import webdriver
from selenium.common import WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route('/')
def root():
    """
    Serve the main static HTML page.

    Returns
    -------
    Response
        The contents of 'main_page.html' from the static folder.
    """
    return app.send_static_file('main_page.html')


def open_browser(browser: str, pqc_mode: int, headless: bool = True):
    """
    Launch a Selenium WebDriver for Chrome or Firefox with PQC prefs.

    Parameters
    ----------
    browser : str
        'chrome' or 'firefox'.
    pqc_mode : int
        0 = Non‑PQC (disable/avoid PQC experiments)
        1 = Kyber (TLS 1.3 Kyber/Hybrid)
        2 = MLKEM (Chrome's ML‑KEM experiment)
    headless : bool, default True
        Whether to run browser in headless mode.

    Returns
    -------
    WebDriver
        An instance of Chrome or Firefox WebDriver.

    Raises
    ------
    ValueError
        If pqc_mode is not one of {0,1,2}.
    BrowserLaunchError
        If the driver fails to start or browser is not installed.
    """
    if pqc_mode not in (0, 1, 2):
        raise ValueError(f"pqc_mode must be 0 (Non-PQC), 1 (Kyber), or 2 (MLKEM); got {pqc_mode}")

    chrome_opts = webdriver.ChromeOptions()
    firefox_opts = webdriver.FirefoxOptions()

    chrome_local_state_prefs = {"browser": {"enabled_labs_experiments": []}}

    if headless:
        # Headless Chrome
        chrome_opts.add_argument("--headless=new")
        chrome_opts.add_argument("--disable-gpu")  # Windows workaround
        chrome_opts.add_argument("--no-sandbox")  # Linux container workaround
        # Headless Firefox
        firefox_opts.add_argument("-headless")

    subprocess.run(['echo', "PQC mode confirmation: " + str(pqc_mode)])
    # ----- Chrome PQC experiments (via Local State "enabled_labs_experiments") -----
    if pqc_mode == 0:
        chrome_local_state_prefs["browser"]["enabled_labs_experiments"] = [
            "enable-tls13-kyber@2",
            "use-ml-kem@2"]

    elif pqc_mode == 1:
        chrome_local_state_prefs["browser"]["enabled_labs_experiments"] = [
            "use-ml-kem@2"]
    elif pqc_mode == 2:  # ML-KEM
        chrome_local_state_prefs["browser"]["enabled_labs_experiments"] = [
            "enable-tls13-kyber@2",  # Disabled
            "use-ml-kem@1",  # Enabled
        ]

    user_data_dir = os.path.abspath(os.path.join(os.getcwd(), "tmp_chrome_profile"))
    shutil.rmtree(user_data_dir, ignore_errors=True)
    os.makedirs(user_data_dir, exist_ok=True)

    chrome_opts.add_argument(f"--user-data-dir={user_data_dir}")
    chrome_opts.add_experimental_option("localState", chrome_local_state_prefs)

    # ----- Firefox PQC prefs -----
    # Kyber toggles exist; MLKEM toggle generally doesn't. We only flip Kyber flags.
    enable_kyber = (pqc_mode == 1)
    firefox_opts.set_preference('network.http.http3.enable_kyber', enable_kyber)
    firefox_opts.set_preference('security.tls.enable_kyber', enable_kyber)

    # ----- Launch -----
    if browser.lower() == 'chrome':
        try:
            subprocess.run(['echo', 'Trying to open chrome'])

            if platform_module.system() == 'Linux':
                subprocess.run(['echo', 'Identified we are in Linux'])
                chromedriver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/local/bin/chromedriver")
                subprocess.run(['echo', 'Found chromeService install' + chromedriver_path])
            else:
                chromedriver_path = ChromeDriverManager().install()

            service = ChromeService(executable_path=chromedriver_path)
            subprocess.run(['echo', 'Returning the webdriver'])
            return webdriver.Chrome(service=service, options=chrome_opts)
        except WebDriverException as e:
            subprocess.run(['echo', "Failed to open Chrome: is Chrome installed and the driver up to date?"])
            raise BrowserLaunchError(
                "Failed to open Chrome: is Chrome installed and the driver up to date?") from e

    try:
        gecko_path = GeckoDriverManager().install()
        return webdriver.Firefox(service=FirefoxService(gecko_path), options=firefox_opts)
    except WebDriverException as e:
        raise BrowserLaunchError(
            "Failed to open Firefox: is Firefox installed and the driver up to date?") from e


def process_session(browser: str, pqc: bool, algo: str | None, amount: int, domain: str):
    """
    Execute a browsing and packet-capture session over multiple iterations.

    For each iteration:
    2. Launch the browser to visit the domain.
    3. Split streams and filter by IPs.
    4. Save pcaps with more than 20 packets to the final directory.

    Parameters
    ----------
    browser : str
        'chrome' or 'firefox'.
    pqc : bool
        Enable post-quantum experiments.
    algo : str or None
        Algorithm to enable.
    amount : int
        Number of successful captures to store.
    domain : str
        Target domain to visit.

    Returns
    -------
    dict
        JSON-serializable result with 'status' and 'directory' keys.
    """

    if pqc is False:
        pqc_mode = 0
    elif algo.lower() == "kyber":
        pqc_mode = 1
    elif algo.lower() == "mlkem":
        pqc_mode = 2
    else:
        pqc_mode = 0

    subprocess.run(['echo', "Algo mode is: " + algo])
    subprocess.run(['echo', "PQC mode is: " + str(pqc_mode)])

    final_dir = name_dir(browser, pqc_mode)

    if os.path.isdir(final_dir):
        shutil.rmtree(final_dir)
    os.makedirs(final_dir, exist_ok=True)
    address = socket.getaddrinfo(domain, None)
    ips = list({addr[4][0] for addr in address})
    exe = sys.executable
    if platform_module.system() != 'Windows':
        subprocess.run(['echo', 'thank you, resuming...'])
    i = 0
    while i < amount:
        sniff_pcap = f'sniff-{i}.pcap'
        proc = subprocess.Popen(cmd)
        subprocess.run(['echo', "About to open the browser..."])
        driver = open_browser(browser, pqc_mode)
        driver.get(f'https://{domain}')
        proc.wait()
        driver.quit()
        outdir = f'temp-{i}'
        split_streams(sniff_pcap, outdir)
        result = loop_thru_all_files_in(outdir, ips)
        if result and result[0] > 20:
            shutil.copy2(result[1], os.path.join(final_dir, f"{i:02}.pcap"))
            i += 1
        shutil.rmtree(outdir, ignore_errors=True)
        os.remove(sniff_pcap)
    return {"status": "done", "directory": final_dir}


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
    # --- parse request (robust to either old or new client formats) ---
    subprocess.run(['echo', "Starting PQBench session..."])
    data = request.get_json() or request.form
    try:
        browser = data['browser']

        raw_pqc = data.get('pqc')  # could be bool/str/int (old/new clients)
        algo = data.get('algorithm')
        # If client passed numeric mode (0/1/2), use it directly

        pqc_mode = 0
        pqc_bool = raw_pqc in [True, 'true', 'True', '1']
        if pqc_bool:
            if algo and algo.lower() == 'kyber':
                pqc_mode = 1
            elif algo and algo.lower() == 'mlkem':
                pqc_mode = 2
            else:  # Fallback
                pqc_mode = 0

        amount = int(data['packets'])
        domain = data.get('domain', 'pq.cloudflareresearch.com')

        if amount <= 0:
            return jsonify('Error: packets must be a positive number')

        if pqc_mode == 0:
            pqc_flag = False
            algo_name = None
        elif pqc_mode == 1:
            pqc_flag = True
            algo_name = "kyber"
        else:
            pqc_flag = True
            algo_name = "mlkem"

        result = process_session(browser, pqc_flag, algo_name, amount, domain)
        return jsonify(result), 200
    except (KeyError, ValueError) as e:
        return jsonify({'Error': f'Bad request: {e}'}), 400
    except BrowserLaunchError as e:
        # This is Browser startup error
        return jsonify({'Error': str(e)}), 500
    except Exception as e:
        # Catch anything else we did’t anticipate
        app.logger.exception(e)
        return jsonify({'Error': 'Unexpected server error'}), 500


class BrowserLaunchError(RuntimeError):
    """Raised when we fail to launch the requested browser."""
    pass


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
