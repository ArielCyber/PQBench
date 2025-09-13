import os
from flask import Flask, request, jsonify
import requests
import logging

import os, socket
from urllib.parse import urlparse

# Sniffer config (env-driven)
SNIFFER_URL = os.getenv("SNIFFER_URL", "http://host.docker.internal:7000")
SNIFFER_IFACE = os.getenv("SNIFFER_IFACE", None)  # e.g., "pqbench0" or None to let sniffer default
SNIFFER_FILTER_MODE = os.getenv("SNIFFER_FILTER_MODE", "domain")  # "none" | "domain" | "custom"
SNIFFER_DOMAIN = os.getenv("SNIFFER_DOMAIN", "pq.cloudflareresearch.com")
SNIFFER_PORTS = os.getenv("SNIFFER_PORTS", None)  # e.g., "443,80"
SNIFFER_DURATION_SEC_DEFAULT = int(os.getenv("SNIFFER_DURATION_SEC", "30"))

ALGO_NAME_TO_CODE = {"non-pqc": 0, "kyber": 1, "mlkem": 2}

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Set the minimum log level
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

app = Flask(__name__, static_folder="static", static_url_path="")

Containers = {
    # compose service names can be used as hosts
    "linux_kyber":  os.getenv("URL_LINUX_KYBER",  "http://linux-kyber:5000"),
    "linux_mlkem":  os.getenv("URL_LINUX_MLKEM",  "http://linux-mlkem:5000"),

    "windows_kyber": os.getenv("URL_WINDOWS_KYBER", "http://windows-kyber:5000"),
    "windows_mlkem": os.getenv("URL_WINDOWS_MLKEM", "http://windows-mlkem:5000"),

    "macos_kyber":  os.getenv("URL_MACOS_KYBER",  "http://macos-kyber:5000"),
    "macos_mlkem":  os.getenv("URL_MACOS_MLKEM",  "http://macos-mlkem:5000"),
}

TARGET_ENDPOINT = "/execute"

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


def choose_container(opsys: str, algo: str) -> str:
    """
    Chooses a container to activate the recording.
    :param opsys: the operating system to record - Linux | Windows | MacOS
    :param browser: the web browser to record - Chrome | Firefox
    :param algo: the algorithm to record - Non-PQC | Kyber | MLKEM
    :return: a key to the right container based on the given arguments.
    """
    opsys = opsys.lower()
    algo = algo.lower()
    logging.debug("os: " + opsys + " algorithm: " + algo)
    if algo == "kyber" or algo == "non-pqc":
        algorithm = "kyber"
    elif algo == "mlkem":
        algorithm = "mlkem"
    else:
        algorithm = "invalid"

    # algorithm = "kyber" if algo == "non-pqc" or algo == "kyber" else "mlkem"

    # activate the desired container
    key = f"{opsys}_{algorithm}"
    logging.debug("The chosen container: " + key)

    # make sure that such container exists
    if key not in Containers:
        raise ValueError(f"No backend configured for combo: {key}")

    return key


@app.route("/config", methods=["POST"])
def config_handler():
    """
    Gets recording characteristics information from the webUI or the agent by a POST request.
    :return: a JSON with the recording information to the right container to navigate to.
    """
    payload = request.get_json(silent=True) or {}

    # --- helpers to normalize inputs ---
    def norm_os(v):
        if v is None:
            return None
        s = str(v).strip().lower()
        return OS_MAP.get(s, s)  # convert code "0"->"linux", or keep "linux" as is

    def norm_algo(v):
        if v is None:
            return None
        s = str(v).strip().lower()
        return ALGO_MAP.get(s, s)  # convert code "1"->"kyber", or keep "kyber" as is

    def norm_browser(v):
        if v is None:
            return None
        return str(v).strip().lower()

    # --- accept both "operationSystem" and "os" ---
    os_raw = payload.get("operationSystem", payload.get("os"))
    browser = norm_browser(payload.get("browser"))
    algo_raw = payload.get("algorithm")
    sessions_raw = payload.get("sessions")

    try:
        opsys = norm_os(os_raw)
        algo = norm_algo(algo_raw)
        sessions = int(sessions_raw) if sessions_raw is not None else 0
        logging.debug(f"Values from JSON POST request: {opsys}, {browser}, {algo}, {sessions}")

    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Bad request: {e}"}), 400

    # --- validate inputs ---
    if opsys not in {"linux", "windows", "macos"}:
        return jsonify({"error": "Invalid operating system"}), 400
    elif browser not in {"chrome", "firefox"}:
        return jsonify({"error": "Invalid web browser"}), 400
    elif algo not in {"kyber", "mlkem", "non-pqc"}:
        return jsonify({"error": "Invalid algorithm"}), 400
    elif sessions <= 0:
        return jsonify({"error": "Invalid number of captures"}), 400

    logging.debug("Values are valid, proceed to choose container")
    try:
        target_key = choose_container(opsys, algo)
        logging.debug(f"Key to the container: {target_key}")
        target_base = Containers[target_key].rstrip("/")
        url = f"{target_base}{TARGET_ENDPOINT}"  # e.g. container_name/run

        # forward info to the chosen container
        info = {
            "os": opsys,
            "browser": browser,
            "algorithm": algo_raw,
            "sessions": sessions
        }

        logging.debug(f"Request sent to: {url}")
        resp = requests.post(url, json=info, timeout=60)

        # resolve backend container IP (for sniffer target)
        logging.debug("Get container IP")
        backend_ip = _resolve_service_ip(target_base)
        logging.debug(f"Container IP {backend_ip}")
        # start sniffer capture for this target
        sniff_status, sniff_body = _start_sniffer_for_target(
            container_ip=backend_ip,
            opsys=opsys,
            browser=browser,
            algo_name=algo,
            duration_sec=None,        # or map from your payload if you add it
            iface="eth0",               # will fall back to env SNIFFER_IFACE
            filter_mode=None,         # env default
            domain=None,              # env default
            ports=None,               # env default
        )

        # 4) Relay a combined response
        try:
            backend_json = resp.json()
        except ValueError:
            backend_json = {"text": resp.text}

        return jsonify({
            "routed_to": target_key,
            "backend": {
                "status": resp.status_code,
                "response": backend_json
            },
            "sniffer": {
                "url": f"{SNIFFER_URL}/start",
                "status": sniff_status,
                "response": sniff_body
            }
        }), resp.status_code

    except requests.RequestException as e:
        return jsonify({"error": f"Switcher couldn't reach backend: {e}"}), 502
    except Exception as e:
        app.logger.exception(e)
        return jsonify({"error": "Unexpected server error"}), 500


def _resolve_service_ip(service_url: str) -> str:
    """
    Extract hostname from 'http://<host>:port' and DNS-resolve it to an IP
    from inside the Docker network (e.g., 172.19.0.x).
    """
    host = urlparse(service_url).hostname
    if not host:
        raise ValueError(f"Invalid service URL: {service_url}")
    return socket.gethostbyname(host)


def _start_sniffer_for_target(
    container_ip: str,
    opsys: str,
    browser: str,
    algo_name: str,
    duration_sec: int | None = None,
    iface: str | None = None,
    filter_mode: str | None = None,
    domain: str | None = None,
    ports: str | None = None,
):
    """
    Build a single-target StartBatchRequest and POST it to the sniffer.
    """
    algo_code = ALGO_NAME_TO_CODE.get(algo_name.lower())
    if algo_code is None:
        raise ValueError(f"Unsupported algorithm for sniffer: {algo_name}")

    payload = {
        "targets": [
            {
                "os": opsys,                         # "linux" | "windows" | "macos"
                "browser": browser,                  # "chrome" | "firefox"
                "algo": algo_code,                   # 0/1/2
                "container_ip": container_ip,        # e.g., "172.19.0.5"
                "duration_sec": duration_sec or SNIFFER_DURATION_SEC_DEFAULT,
                # per-target options
                "iface": iface or SNIFFER_IFACE,
                "filter_mode": (filter_mode or SNIFFER_FILTER_MODE),
                "domain": domain if (filter_mode or SNIFFER_FILTER_MODE) == "domain" else None,
                "ports": ports or SNIFFER_PORTS,
                # "custom_bpf": "...",               # only if you use filter_mode="custom"
            }
        ]
    }

    logging.debug(f"json payload {payload}")

    # remove None fields to keep payload clean
    for t in payload["targets"]:
        for k in list(t.keys()):
            if t[k] is None:
                del t[k]

    resp = requests.post(f"{SNIFFER_URL}/start", json=payload, timeout=30)
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, {"text": resp.text}


@app.route('/done', methods=['POST'])
def done_handler():
    data = request.get_json(force=True)  # {"os": "linux", "browser": "chrome", "algo": 1}
    logging.info(f"Received done payload: {data}")

    # Extract fields
    os_name = data.get("os")
    browser = data.get("browser")
    algo = data.get("algo")

    logging.debug(f"os={os_name}, browser={browser}, algo={algo}")

    # --- Forward to sniffer /done ---
    try:
        chosen = choose_container(os_name, algo)
        payload = {"url": chosen["url"]}

        sniffer_resp = requests.post(
            f"{SNIFFER_URL}/done",
            json=payload,
            timeout=10
        )
        sniffer_resp.raise_for_status()
        sniffer_reply = sniffer_resp.json()
        logging.info(f"Forwarded to sniffer, reply: {sniffer_reply}")
    except Exception as e:
        logging.error(f"Failed to forward to sniffer /done: {e}")
        return jsonify({"status": "error", "reason": str(e)}), 502

    # Return a response JSON
    return jsonify({
        "status": "ok",
        "received": data,
        "sniffer": sniffer_reply
    })




if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
