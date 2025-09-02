import os
from flask import Flask, request, jsonify
import requests
import logging

'''
TODO:
1. add debugging features 
2. tests
3. check networking between 2 containers

docker build -t NAME:latest . 
'''

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Set the minimum log level
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

app = Flask(__name__, static_folder="static", static_url_path="")

Containers = {
    # compose service names can be used as hosts
    "linux_chrome_kyber":  os.getenv("URL_LINUX_CHROME_KYBER",  "http://service-linux-chrome-kyber:8000"),
    "linux_chrome_mlkem":  os.getenv("URL_LINUX_CHROME_MLKEM",  "http://service-linux-chrome-mlkem:8000"),
    "linux_firefox_kyber": os.getenv("URL_LINUX_FIREFOX_KYBER", "http://service-linux-firefox-kyber:8000"),
    "linux_firefox_mlkem": os.getenv("URL_LINUX_FIREFOX_MLKEM", "http://service-linux-firefox-mlkem:8000"),

    "windows_chrome_kyber": os.getenv("URL_WINDOWS_CHROME_KYBER", "http://service-windows-chrome-kyber:8000"),
    "windows_chrome_mlkem": os.getenv("URL_WINDOWS_CHROME_MLKEM", "http://service-windows-chrome-mlkem:8000"),
    "windows_firefox_kyber": os.getenv("URL_WINDOWS_FIREFOX_KYBER", "http://service-windows-firefox-kyber:8000"),
    "windows_firefox_mlkem": os.getenv("URL_WINDOWS_FIREFOX_MLKEM", "http://service-windows-firefox-mlkem:8000"),

    "macos_chrome_kyber":  os.getenv("URL_MACOS_CHROME_KYBER",  "http://service-macos-chrome-kyber:8000"),
    "macos_chrome_mlkem":  os.getenv("URL_MACOS_CHROME_MLKEM",  "http://service-macos-chrome-mlkem:8000"),
    "macos_firefox_kyber": os.getenv("URL_MACOS_FIREFOX_KYBER", "http://service-macos-firefox-kyber:8000"),
    "macos_firefox_mlkem": os.getenv("URL_MACOS_FIREFOX_MLKEM", "http://service-macos-firefox-mlkem:8000"),
}

TARGET_ENDPOINT = "/run"

# map keys to values
OS_MAP = {"0": "linux", "1": "windows", "2": "macos"}
ALGO_MAP = {"0": "non-pqc", "1": "kyber", "2": "mlkem"}


@app.get("/health")
def health():
    return "ok", 200


@app.route("/")
def root():
    logging.debug("Opening the html web")
    return app.send_static_file("main_page.html")


def choose_container(opsys: str, browser: str, algo: str) -> str:
    """
    Chooses a container to activate the recording.
    :param opsys: the operating system to record - Linux | Windows | MacOS
    :param browser: the web browser to record - Chrome | Firefox
    :param algo: the algorithm to record - Non-PQC | Kyber | MLKEM
    :return: a key to the right container based on the given arguments.
    """
    opsys = opsys.lower()
    browser = browser.lower()
    algo = algo.lower()
    logging.debug("os: " + opsys + " browser: " + browser + " algorithm: " + algo)
    if algo == "kyber" or algo == "non-pqc":
        algorithm = "kyber"
    elif algo == "mlkem":
        algorithm = "mlkem"
    else:
        algorithm = "invalid"

    # algorithm = "kyber" if algo == "non-pqc" or algo == "kyber" else "mlkem"

    # activate the desired container
    key = f"{opsys}_{browser}_{algorithm}"
    logging.debug("The chosen container: " + key)

    # make sure that such container exists
    if key not in Containers:
        raise ValueError(f"No backend configured for combo: {key}")

    return key


@app.route("/config", methods=["POST"])
def config_handler():
    """
    Gets recording characteristics information from the webUI or the agent by a POST request.
    :return: a json with the recording information to the right container to navigate to.
    """
    data = request.get_json(silent=True) or {}

    try:
        # get values from html request
        os_code = str(data.get("operationSystem")).lower()
        browser = str(data["browser"]).lower()
        algo_code = str(data["algorithm"]).lower()
        sessions = int(data["sessions"])
        logging.debug(f"Values from json POST request: {os_code}, {browser}, {algo_code}, {sessions}")

    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"error": f"Bad request: {e}"}), 400

    # map values by keys
    opsys = OS_MAP.get(os_code)
    algo = ALGO_MAP.get(algo_code)

    # validate inputs
    if opsys not in {"linux", "windows", "macos"}:
        return jsonify({"error": "Invalid operating system"}), 401

    elif browser not in {"chrome", "firefox"}:
        return jsonify({"error": "Invalid web browser"}), 401

    elif algo not in {"kyber", "mlkem", "non-pqc"}:
        return jsonify({"error": "Invalid algorithm"}), 401

    elif sessions <= 0:
        return jsonify({"error": "Invalid number of captures"}), 401

    try:
        target_key = choose_container(opsys, browser, algo)
        logging.debug("Key to the right container chosen")
        target_base = Containers[target_key].rstrip("/")
        logging.debug("Container chosen to route")
        url = f"{target_base}{TARGET_ENDPOINT}"
        logging.debug(f"Got the container URL: {url}")

        # forward info to the chosen container
        info = {
            "os": opsys,
            "browser": browser,
            "algorithm": algo,
            "sessions": sessions
        }

        resp = requests.post(url, json=info, timeout=60)

        # relay backend response
        try:
            backend_json = resp.json()
            return jsonify({
                "routed_to": target_key,
                "backend_status": resp.status_code,
                "backend_response": backend_json
            }), resp.status_code

        except ValueError:
            return jsonify({
                "routed_to": target_key,
                "backend_status": resp.status_code,
                "backend_response_text": resp.text
            }), resp.status_code

    except requests.RequestException as e:
        return jsonify({"error": f"Router couldn't reach backend: {e}"}), 502

    except Exception as e:
        app.logger.exception(e)
        return jsonify({"error": "Unexpected server error"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
