import logging
import os
import sys
import winreg
from pathlib import Path

from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.common import WebDriverException
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.firefox import GeckoDriverManager

app = Flask(__name__)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)])


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
            "enable-tls13-kyber@2"]

    elif algo == 1:
        prefs["browser"]["enabled_labs_experiments"] = [
            "enable-tls13-kyber@1"]

    chrome_opts.add_experimental_option("localState", prefs)

    try:
        chromedriver_path = ChromeDriverManager().install()
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
            # Wait until document is fully ready (or a small dwell)
            logging.debug(f"Waiting for the web driver")
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete")
            #sleep(3)
        finally:
            driver.quit()

    return {"status": "done"}


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
