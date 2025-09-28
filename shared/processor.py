import logging
import os
import sys
from pathlib import Path
from time import sleep
from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.common import WebDriverException
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.firefox import GeckoDriverManager
from webdriver_manager.chrome import ChromeDriverManager

app = Flask(__name__)

# === Logging setup ===
log_path = os.getenv("PY_LOG_FILE", "processor.log")
Path(log_path).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# === Route: Serve correct HTML based on MODE ===
@app.route('/')
def root():
    mode = os.getenv("MODE", "KYBER").upper()
    if mode == "MLKEM":
        return app.send_static_file('mlkem_page.html')
    return app.send_static_file('kyber_page.html')

# === Browser decision logic ===
def open_browser(browser: str, algo: int):
    try:
        return open_chrome(algo) if browser.lower() == 'chrome' else open_firefox(algo)
    except WebDriverException as e:
        raise BrowserLaunchError(str(e)) from e

# === Firefox ===
def open_firefox(algo: int):
    firefox_opts = webdriver.FirefoxOptions()
    firefox_opts.add_argument("-headless")

    if algo == 0:
        firefox_opts.set_preference('network.http.http3.enable_kyber', False)
        firefox_opts.set_preference('security.tls.enable_kyber', False)
    else:
        firefox_opts.set_preference('security.tls.enable_kyber', True)
        firefox_opts.set_preference('network.http.http3.enabled', True)
        firefox_opts.set_preference('network.http.http3.enable_kyber', True)

    binary_path = "/Applications/Firefox 130.app/Contents/MacOS/firefox" if algo in [0, 1] \
                  else "/Applications/Firefox 142.app/Contents/MacOS/firefox"
    firefox_opts.binary_location = binary_path

    gecko_path = GeckoDriverManager().install()
    return webdriver.Firefox(service=FirefoxService(gecko_path), options=firefox_opts)

# === Chrome ===
def open_chrome(algo: int):
    chrome_opts = webdriver.ChromeOptions()
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--headless=new")
    chrome_opts.add_argument("--disable-gpu")
    chrome_opts.add_argument("--disable-dev-shm-usage")
    chrome_opts.add_argument("--remote-debugging-port=0")

    prefs = {"browser": {"enabled_labs_experiments": []}}
    mode = os.getenv("MODE", "KYBER").upper()

    if algo == 0:
        prefs["browser"]["enabled_labs_experiments"] = ["enable-tls13-kyber@2", "use-ml-kem@2"]
        chrome_path = "/Applications/Google Chrome 128.app/Contents/MacOS/Google Chrome for Testing"
        chromedriver_path = "/usr/local/bin/chromedriver-128.0.6613.137"

    elif algo == 1:
        prefs["browser"]["enabled_labs_experiments"] = ["enable-tls13-kyber@1", "use-ml-kem@2"]
        chrome_path = "/Applications/Google Chrome 128.app/Contents/MacOS/Google Chrome for Testing"
        chromedriver_path = "/usr/local/bin/chromedriver-128.0.6613.137"

    elif algo == 2:
        prefs["browser"]["enabled_labs_experiments"] = ["enable-tls13-kyber@2", "use-ml-kem@1"]
        chrome_path = "/Applications/Google Chrome 138.app/Contents/MacOS/Google Chrome for Testing"
        chromedriver_path = "/usr/local/bin/chromedriver-138.0.7204.183"
    else:
        raise ValueError(f"Unknown algorithm value: {algo}")

    chrome_opts.add_experimental_option("localState", prefs)
    chrome_opts.binary_location = chrome_path

    return webdriver.Chrome(options=chrome_opts, service=ChromeService(chromedriver_path))

# === Main browser session logic ===
def process_session(browser: str, algo: int, amount: int, domain: str):
    for _ in range(amount):
        driver = open_browser(browser, algo)
        driver.get(f'https://{domain}')
        WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete")
        sleep(5)
        driver.quit()
    return {"status": "done"}

# === POST /config ===
@app.route('/config', methods=['POST'])
def config_handler():
    logging.info("Starting PQBench session...")
    data = request.get_json() or request.form
    try:
        browser = data['browser']
        algo = int(data['algorithm'])
        amount = int(data['sessions'])
        domain = data.get('domain', 'pq.cloudflareresearch.com')
        if amount <= 0:
            raise ValueError("Session count must be > 0")
        return jsonify(process_session(browser, algo, amount, domain)), 200
    except (KeyError, ValueError) as e:
        return jsonify({'Error': str(e)}), 400
    except BrowserLaunchError as e:
        return jsonify({'Error': str(e)}), 500
    except Exception as e:
        logging.exception("Unexpected error")
        return jsonify({'Error': 'Unexpected server error'}), 500

# === Exception Class ===
class BrowserLaunchError(RuntimeError):
    pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
