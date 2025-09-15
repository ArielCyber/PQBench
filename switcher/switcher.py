import os
from flask import Flask, request, jsonify, Response, json
import requests
import logging

import os, socket
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore
from collections import defaultdict

# one-at-a-time per backend key
_backend_slots = defaultdict(lambda: Semaphore(1))
# modest concurrency across different backends
_EXECUTOR = ThreadPoolExecutor(max_workers=10)

# Sniffer config (env-driven)
SNIFFER_URL = os.getenv("SNIFFER_URL", "http://172.18.0.1:8080")
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
    "linux_kyber": os.getenv("URL_LINUX_KYBER", "http://linux-kyber:5000"),
    "linux_mlkem": os.getenv("URL_LINUX_MLKEM", "http://linux-mlkem:5000"),

    "windows_kyber": os.getenv("URL_WINDOWS_KYBER", "http://windows-kyber:5000"),
    "windows_mlkem": os.getenv("URL_WINDOWS_MLKEM", "http://windows-mlkem:5000"),

    "macos_kyber": os.getenv("URL_MACOS_KYBER", "http://macos-kyber:5000"),
    "macos_mlkem": os.getenv("URL_MACOS_MLKEM", "http://macos-mlkem:5000"),
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


    """
    This function expects to get a JSON with a "jobs" field which contains
    all the recording information for each container (os, browser, algo, seesions etc.)
    A single json without jobs field is considered as a single recording
    """


@app.route("/config", methods=["POST"])
def config_handler():

    payload = request.get_json(silent=True) or {}

    # read incoming json (single or a batch)
    raw_jobs = payload.get("jobs")
    if raw_jobs is None:
        raw_jobs = [payload]  # single job backward-compat

    # helper functions
    def pick(d, *keys):  # returns the first present key
        for k in keys:
            if k in d and d[k] is not None:
                return d[k]
        return None

    # normalization functions
    def norm_os(v):
        if v is None:
            return None
        s = str(v).strip().lower()
        return OS_MAP.get(s, s)

    def norm_algo(v):
        if v is None:
            return None
        s = str(v).strip().lower()
        return ALGO_MAP.get(s, s)

    def norm_browser(v):
        if v is None:
            return None
        return str(v).strip().lower()

    # parse each job
    jobs = []
    errors = []
    for idx, j in enumerate(raw_jobs):
        os_raw = pick(j, "operationSystem", "os")
        browser = norm_browser(pick(j, "browser"))
        algo_name = norm_algo(pick(j, "algorithm", "algo"))
        sessions_raw = pick(j, "sessions", "session", "count")
        logging.debug(f"Sessions raw: {sessions_raw}")

        try:
            opsys = norm_os(os_raw)
            if isinstance(sessions_raw, str):
                sessions_raw = sessions_raw.strip()
            if sessions_raw is None or (isinstance(sessions_raw, str) and not sessions_raw.isdigit()):
                raise ValueError("sessions must be an integer > 0")
            sessions = int(sessions_raw)
        except Exception as e:
            errors.append({"index": idx, "error": f"Bad job: {e}"})
            continue

        # validate
        if opsys not in {"linux", "windows", "macos"}:
            errors.append({"index": idx, "error": "Invalid operating system"});
            continue
        if browser not in {"chrome", "firefox"}:
            errors.append({"index": idx, "error": "Invalid web browser"});
            continue
        if algo_name not in {"kyber", "mlkem", "non-pqc"}:
            errors.append({"index": idx, "error": "Invalid algorithm"});
            continue
        if sessions <= 0:
            errors.append({"index": idx, "error": "Invalid sessions"});
            continue

        try:
            key = choose_container(opsys, algo_name)
        except Exception as e:
            errors.append({"index": idx, "error": str(e)})
            continue

        algo_code = ALGO_NAME_TO_CODE.get(algo_name.lower())
        target_base = Containers[key].rstrip("/")
        jobs.append({
            "idx": idx,
            "opsys": opsys,
            "browser": browser,
            "algo_name": algo_name,   # string
            "algo_code": algo_code,   # int
            "sessions": sessions,
            "target_key": key,
            "target_base": target_base
        })

    if not jobs:
        return jsonify({"error": "No valid jobs", "detail": errors}), 400

    # ----- resolve backend IPs and build sniffer targets (dedup) -----
    sniffer_targets = []
    seen = set()
    for jb in jobs:
        ip = _resolve_service_ip(jb["target_base"])
        # build code e.g. "121" using your existing name_dir mapping
        algo_code = ALGO_NAME_TO_CODE[jb["algo_name"]]
        code = generate_code(jb["opsys"], jb["browser"], algo_code)
        key = (ip, code)
        if key in seen:  # avoid double-sniffing exact same (container,code)
            continue
        seen.add(key)
        tgt = {
            "os": jb["opsys"],
            "browser": jb["browser"],
            "algo": algo_code,
            "container_ip": ip,
            "duration_sec": SNIFFER_DURATION_SEC_DEFAULT,
            "iface": SNIFFER_IFACE,  # or omit to let sniffer default
            "filter_mode": SNIFFER_FILTER_MODE,
            "domain": SNIFFER_DOMAIN if SNIFFER_FILTER_MODE == "domain" else None,
            "ports": SNIFFER_PORTS
        }
        # strip Nones
        for k in list(tgt.keys()):
            if tgt[k] is None:
                del tgt[k]
        sniffer_targets.append(tgt)

    # ----- arm sniffer batch first -----
    sniffer_payload = {"targets": sniffer_targets} if sniffer_targets else {"targets": []}
    try:
        sresp = requests.post(f"{SNIFFER_URL}/start", json=sniffer_payload, timeout=30)
        try:
            sniffer_body = sresp.json()
        except ValueError:
            sniffer_body = {"text": sresp.text}
    except requests.RequestException as e:
        # sniffer failed; we can still try backends, but report the failure
        sresp = type("obj", (), {"status_code": 502})
        sniffer_body = {"error": f"sniffer unreachable: {e}"}

    # ----- fan-out backend executions with per-backend serialization -----
    results = [None] * len(raw_jobs)

    def run_one(jb):
        sem = _backend_slots[jb["target_key"]]
        with sem:
            info = {
                "os": jb["opsys"],
                "browser": jb["browser"],
                "algorithm": jb["algo_code"],
                "sessions": jb["sessions"]
            }
            url = f'{jb["target_base"]}{TARGET_ENDPOINT}'
            try:
                r = requests.post(url, json=info, timeout=60)
                try:
                    body = r.json()
                except ValueError:
                    body = {"text": r.text}
                return {"status": r.status_code, "response": body, "routed_to": jb["target_key"]}
            except requests.RequestException as e:
                return {"status": 502, "response": {"error": f"backend unreachable: {e}"},
                        "routed_to": jb["target_key"]}

    futures = {_EXECUTOR.submit(run_one, jb): jb for jb in jobs}
    for fut in as_completed(futures):
        jb = futures[fut]
        res = fut.result()
        results[jb["idx"]] = res

    # include any per-job parse errors, aligned by index
    for err in errors:
        i = err["index"]
        results_len = max(len(results), i + 1)
        if len(results) < results_len:
            results.extend([None] * (results_len - len(results)))
        results[i] = {"status": 400, "response": err, "routed_to": None}

    payload_out = {
        "sniffer": {"url": f"{SNIFFER_URL}/start", "status": getattr(sresp, "status_code", 0),
                    "response": sniffer_body},
        "backends": results
    }
    # force pretty JSON output
    pretty_json = json.dumps(payload_out, indent=2, ensure_ascii=False)
    return Response(pretty_json, status=207, mimetype="application/json") # Multi-Status: mixed per-job outcomes


def generate_code(os_name: str, browser: str, algo: int) -> str:
    """
    Encode OS, browser, and algorithm into a 3-digit session code.

    Mapping:
        OS: linux=1, windows=2, macos=3
        Browser: firefox=1, chrome=2
        Algo: Non-PQC=0, Kyber=1, MLKEM=2

    Args:
        os_name: OS label.
        browser: Browser label.
        algo: Algorithm code.

    Returns:
        A three-character string like ``"121"``.

    Raises:
        ValueError: If an unsupported OS or browser label is provided.
    """
    os_map = {"linux": "1", "windows": "2", "macos": "3"}
    browser_map = {"firefox": "1", "chrome": "2"}
    try:
        os_num = os_map[os_name.lower()]
        browser_num = browser_map[browser.lower()]
    except KeyError as e:
        logging.error(f"name_dir invalid input: {e}")
        raise ValueError(f"Invalid input: {e.args[0]}")

    code = f"{os_num}{browser_num}{algo}"
    logging.debug(f"name_dir -> os={os_name} browser={browser} algo={algo} => {code}")
    return code


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
        sessions: int,
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

    logging.debug(f"algo name: {algo_name}")
    logging.debug(f"algo code: {algo_code}")
    payload = {
        "targets": [
            {
                "os": opsys,  # "linux" | "windows" | "macos"
                "browser": browser,  # "chrome" | "firefox"
                "algo": algo_code,  # 0/1/2
                "container_ip": container_ip,  # e.g., "172.19.0.5"
                "duration_sec": duration_sec or SNIFFER_DURATION_SEC_DEFAULT,
                "session_count": sessions,
                # per-target options
                "filter_mode": "domain",
                "iface": iface,
                "domain": domain if (filter_mode or SNIFFER_FILTER_MODE) == "domain" else None,
                # "ports": ports or SNIFFER_PORTS,
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
        key = choose_container(os_name,
                               "kyber" if algo in ("kyber", 1) else ("mlkem" if algo in ("mlkem", 2) else "non-pqc"))
        base_url = Containers[key].rstrip("/")
        backend_ip = _resolve_service_ip(base_url)

        payload = {
            # send both; sniffer prefers container_ip, can fall back to url
            "container_ip": backend_ip,
            "url": base_url
        }

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
