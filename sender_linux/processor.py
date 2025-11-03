import logging
import os
import sys
import time
from typing import Dict, Optional

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


@app.get("/health")
def health():
    """
    Health check, if the service is alive returns ok with 200 code
    """
    return "ok", 200


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
    return None


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
    Launch a Selenium WebDriver for Firefox with a given algorithm.
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
    """
    Launch a Selenium WebDriver for Chrome with a given algorithm.
    """
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


def process_session(browser: str, algo: int, amount: int, domain: str, attribute: str):
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

    # Testing scenario:
    domain = "https://www.israelhayom.co.il/you-may-find-interesting/article/17184917"
    attribute = 'video'
    button_values = get_button_values(domain, attribute)

    # Safely extract button values from the dictionary
    shadow_button_class = ""
    play_button_class = ""
    if button_values:  # Check if the dictionary is not None
        shadow_button_class = button_values.get("shadow_class", "")
        play_button_class = button_values.get("play_class", "")

    for i in range(amount):
        driver = open_browser(browser, algo)
        logging.debug(f"The driver opened: {driver}")
        if shadow_button_class:
            click_shadow_button(shadow_button_class, driver)
        if play_button_class:
            click_play_button(play_button_class, driver)
        played = play_video(driver)
        # driver.get(f'https://{domain}')
        logging.debug(f"The driver opened the given domain")

        if play_button_class or not played:
            try_iframes(driver, play_button_class)
        try:
            # Wait until document is fully ready (or a small dwell)
            logging.debug(f"Waiting for the web driver")
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete")
            time.sleep(3)
        finally:
            driver.quit()

    return {"status": "done"}


@app.route('/execute', methods=['POST'])
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
        attribute = data.get('attribute')
    except (KeyError, ValueError) as e:
        logging.error(f"Bad request: {e}")
        return jsonify({'Error': f'Bad request: {e}'}), 400

    if amount <= 0:
        logging.error("Sessions count must be greater than 0.")
        return jsonify('Error: session count must be a positive number')

    try:
        response = process_session(browser, algo, amount, domain, attribute)
        return jsonify(response), 200
    except BrowserLaunchError as e:
        # This is Browser startup error
        result = jsonify({'Error': str(e)}), 500
        logging.error(f"{e}")
        return result
    except Exception as e:
        # Catch anything else we didn’t anticipate
        app.logger.exception(e)
        logging.error(f"{e}")
        return jsonify({'Error': f'Unexpected server error: {e}'}), 500


def click_shadow_button(shadow_class, driver):
    logging.debug("############### shadow_button ##############  ")
    try:
        shadow_hosts = driver.execute_script("""
            return Array.from(document.querySelectorAll("*"))
                .filter(el => el.shadowRoot !== null);
        """)
        if not shadow_hosts:
            logging.error(f"No shadow_hosts")
        for host in shadow_hosts:
            clicked = driver.execute_script("""
                const footer = arguments[0];
                const selector = arguments[1];
                const root = footer.shadowRoot;
                if (!root) return false;
                const btn = root.querySelector(selector);
                if (btn) {
                    btn.focus();
                    btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
                    btn.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                    btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                    return true;
                }
                return false;
            """, host, shadow_class)
            if clicked:
                logging.info(f"Clicked '{shadow_class}'")
                return
            else:
                logging.error(f"Couldn't find '{shadow_class}'")
    except Exception as e:
        logging.error("No shadow DOM found")


def click_play_button(play_class, driver, tries=0):
    logging.debug("############# click_play_button ############  ")
    time.sleep(2)
    groups = [name.strip() for name in play_class.split(",") if name.strip()]
    name_done = [False for _ in range(len(groups))]
    not_found_so_unloaded = True
    tries += 1
    for i, group in enumerate(groups):
        for originalName in [a.strip() for a in group.split("|") if a.strip()]:
            name = originalName
            idx = 0
            m = CLASS_INDEX_RE.match(originalName)
            if m:
                name = m.group("class")
                idx = int(m.group("idx"))
            try:
                if name.startswith(":"):
                    elements = driver.find_elements(By.XPATH,
                                                    f"//button[contains(normalize-space(string()),'{name[1:]}')]")
                else:
                    elements = driver.find_elements(By.CLASS_NAME, name)
                if not elements and not name.startswith(":"):
                    elements = driver.find_elements(By.ID, name)
                if elements:
                    not_found_so_unloaded = False
                else:
                    logging.error("No element found")
                    raise Exception("no elements found")
                if idx < 0 or idx >= len(elements):
                    logging.debug(
                        f"Class/Name '{name}' has {len(elements)} elements; index {idx} is out of range")
                    continue
                for element in elements[idx:]:
                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                        time.sleep(0.5)
                        if element.tag_name.lower() == "audio": return element
                        element.click()
                        logging.info(f"Clicked '{name}'")
                        play_class = after_click(play_class, group)
                        name_done[i] = True
                        time.sleep(3)
                        break
                    except:
                        continue
            except Exception as e:
                logging.error(f"Couln't find {name}")
                continue
            if name_done[i]:
                break
    if not_found_so_unloaded:
        if tries > 0:
            logging.error(f"Unloaded '{play_class}'")
            return False
        click_play_button(play_class, driver, tries)
    for curNameDone in name_done:
        if curNameDone:
            return True
    return False


def after_click(play_class, name):
    return ",".join([c for c in play_class.split(",") if c.strip() != name])


def play_video(driver):
    try:
        wait_time = 10
        driver.find_element(By.TAG_NAME, "video")
        time.sleep(2)
        driver.execute_script("""
                    const video = document.querySelector('video');
                    if (video) {
                        video.muted = true;
                        video.play().catch(() => {});
                    }
                """)
        time.sleep(wait_time)
        logging.info(f"Captured <Video> for {wait_time} seconds...")
        return True
    except NoSuchElementException:
        logging.error(f"Failed to play <Video>")
        return False


def get_button_values(domain: str, attribute: str, base_url: str = "http://domain_maintainer:5010") -> Optional[
    Dict[str, str]]:
    """
    Fetches button values for a given domain and attribute by making a GET request
    to the domain_maintainer service.

    Args:
        domain: The domain to search for (e.g., "youtube.com").
        attribute: The attribute (worksheet) to search within (e.g., "video").
        base_url: The base URL of the domain_maintainer service.

    Returns:
        A dictionary containing the values from the first and second columns
        (e.g., {"value_col_1": "...", "value_col_2": "..."}) if found.
        Returns None if the domain is not found or if an error occurs.
    """
    if not domain or not attribute:
        logging.error("Domain and attribute cannot be empty.")
        return None

    endpoint = f"{base_url}/get_button_by_domain/"
    params = {"domain": domain, "attribute": attribute}

    try:
        # Send the GET request
        response = requests.get(endpoint, params=params)

        # Raise an exception for bad status codes (4xx or 5xx)
        response.raise_for_status()

        # Return the JSON response, which should be the dictionary of values
        return response.json()

    except requests.exceptions.HTTPError as e:
        # Specifically handle cases where the server returns an error (like 404 Not Found)
        if e.response.status_code == 404:
            print(f"Info: Domain '{domain}' not found in attribute '{attribute}'.")
        else:
            print(f"HTTP Error fetching button values: {e}")
        return None
    except requests.exceptions.RequestException as e:
        # Handle other network-related errors
        print(f"Error fetching button values: {e}")
        return None
    except ValueError:  # Catches JSON decoding errors
        print("Error: Failed to decode JSON response from the server.")
        return None


######################################################################
# try_iframes and handle_iframe can call each other, has to be changed
# seems like a bad practice
######################################################################


def try_iframes(driver, play_class):
    logging.debug(f"################## iframe ##################")
    driver.switch_to.default_content()
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for iframe in iframes:
        if handle_iframe(iframe, driver, play_class):
            return True
    return False


def handle_iframe(iframe, driver, play_class):
    try:
        driver.switch_to.frame(iframe)
        time.sleep(2)
        clicked = click_play_button(play_class, driver)
        if clicked and not click_out_of_iframe(play_class, driver):
            try_iframes(driver, play_class)
        time.sleep(2)
        if clicked and play_video(driver):
            driver.switch_to.default_content()
            return True
        driver.switch_to.default_content()
    except:
        driver.switch_to.default_content()
    return False


def click_out_of_iframe(play_class, driver):
    if not play_class:
        return True
    driver.switch_to.default_content()
    clicked = click_play_button(play_class, driver)
    time.sleep(2)
    play_video(driver)
    return clicked


class BrowserLaunchError(RuntimeError):
    """Raised when we fail to launch the requested browser."""
    pass


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
