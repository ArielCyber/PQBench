import logging
import os
import sys
from time import sleep

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


@app.route('/')
def root():
    """
    Serve the main static HTML page.

    Returns
    -------
    Response
        The contents of 'kyber_page.html' from the static folder.
    """
    return app.send_static_file('kyber_page.html')


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
    Uses Firefox 130 for algo 0 and 1, Firefox 142 for algo 2.
    """
    logging.debug("Trying to open Firefox")

    firefox_opts = webdriver.FirefoxOptions()

    # Headless mode
    firefox_opts.add_argument("-headless")

    if algo == 0:
        firefox_opts.set_preference('network.http.http3.enable_kyber', False)
        firefox_opts.set_preference('security.tls.enable_kyber', False)
        logging.debug("Set non PQC preferences")
    elif algo in [1, 2]:  # Enable Kyber or MLKEM (Same flags)
        firefox_opts.set_preference("security.tls.enable_kyber", True)
        firefox_opts.set_preference("network.http.http3.enabled", True)
        firefox_opts.set_preference("network.http.http3.enable_kyber", True)
        logging.debug("Set PQC on")

    try:
        # Select Firefox binary based on algo
        if algo in [0, 1]:
            firefox_path = "/Applications/Firefox 130.app/Contents/MacOS/firefox"
        else:
            firefox_path = "/Applications/Firefox 142.app/Contents/MacOS/firefox"

        gecko_path = GeckoDriverManager().install()
        logging.debug(f"Using Firefox binary at: {firefox_path}")
        logging.debug("Installed GeckoDriverManager successfully!")

        return webdriver.Firefox(
            service=FirefoxService(gecko_path),
            options=firefox_opts,
            firefox_binary=firefox_path
        )
    except WebDriverException as e:
        logging.critical(e)
        raise BrowserLaunchError("Failed to open Firefox: is Firefox installed and the driver up to date?") from e



def open_chrome(algo):
    """
    Launch a Selenium WebDriver for Chrome with a given Algo.
    Uses a specific Chrome binary based on the algo parameter:
    - algo 0 or 1: Chrome 128
    - algo 2: Chrome 138
    """
    chrome_opts = webdriver.ChromeOptions()

    # Headless Chrome options
    chrome_opts.add_argument("--no-sandbox")  # containers often need this
    chrome_opts.add_argument("--headless=new")
    chrome_opts.add_argument("--disable-gpu")  # Windows workaround
    chrome_opts.add_argument("--disable-dev-shm-usage")
    chrome_opts.add_argument("--remote-debugging-port=0")  # avoids DevTools port collision

    prefs = {"browser": {"enabled_labs_experiments": []}}

    if algo in [0, 1]:
        # Non-PQC or Kyber-only — use Chrome 128
        prefs["browser"]["enabled_labs_experiments"] = [
            "enable-tls13-kyber@2",  # explicitly disabled
            "use-ml-kem@2"           # explicitly disabled
        ]
        chrome_path = "/Applications/Google Chrome 128.app/Contents/MacOS/Google Chrome"
    elif algo == 2:
        # ML-KEM (PQC) — use Chrome 138
        prefs["browser"]["enabled_labs_experiments"] = [
            "enable-tls13-kyber@2",  # explicitly disabled
            "use-ml-kem@1"           # enabled
        ]
        chrome_path = "/Applications/Google Chrome 138.app/Contents/MacOS/Google Chrome"
    else:
        raise ValueError(f"Unknown algorithm value: {algo}")

    chrome_opts.add_experimental_option("localState", prefs)
    chrome_opts.binary_location = chrome_path

    try:
        chromedriver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/local/bin/chromedriver")
        service = ChromeService(executable_path=chromedriver_path)
        return webdriver.Chrome(options=chrome_opts, service=service)
    except WebDriverException as e:
        logging.critical(e)
        raise BrowserLaunchError("Failed to open Chrome: is Chrome installed and the driver up to date?") from e



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

    for i in range(amount):
        driver = open_browser(browser, algo)
        logging.debug(f"The driver opened: {driver}")
        driver.get(f'https://{domain}')
        logging.debug(f"The driver opened the given domain")

        try:
            # Wait until DOM is complete
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete")
            logging.debug("Page DOM complete")

            # Dwell a bit to let scripts/network calls finish
            sleep(5)

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
        domain = data.get('domain', 'pq.cloudflareresearch.com')
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
