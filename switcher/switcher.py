import json
import logging
import os
import socket
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore
from urllib.parse import urlparse
from typing import Dict, List, Union

import requests
from flask import Flask, request, json
from flask import Response

# one-at-a-time per backend key
_backend_slots = defaultdict(lambda: Semaphore(1))
# modest concurrency across different backends
_EXECUTOR = ThreadPoolExecutor(max_workers=10)

# Sniffer config (env-driven)
SNIFFER_URL = os.getenv("SNIFFER_URL", "http://172.18.0.1:8080")
SNIFFER_FILTER_MODE = "domain"
SNIFFER_DOMAIN = "israelhayom.co.il/you-may-find-interesting/article/17184917"

ALGO_NAME_TO_CODE = {"non-pqc": 0, "kyber": 1, "mlkem": 2}

LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()
# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

app = Flask(__name__, static_folder="static", static_url_path="")

Containers = {
    # compose service names can be used as hosts
    "linux_kyber": os.getenv("URL_LINUX_KYBER", "http://linux-kyber:5000"),
    "linux_mlkem": os.getenv("URL_LINUX_MLKEM", "http://linux-mlkem:5000"),

    "windows_kyber": os.getenv("URL_WINDOWS_KYBER", "http://win-kyber:5000"),
    "windows_mlkem": os.getenv("URL_WINDOWS_MLKEM", "http://win-mlkem:5000"),

    "macos_kyber": os.getenv("URL_MACOS_KYBER", "http://macos-kyber:5000"),
    "macos_mlkem": os.getenv("URL_MACOS_MLKEM", "http://macos-mlkem:5000"),
}

TARGET_ENDPOINT = "/execute"
TARGET_DONE_ENDPOINT = "/done"

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
    logging.info("config_handler: received payload: %s", payload)

    # ---------- accept single or batch ----------
    raw_jobs = payload.get("jobs")
    if raw_jobs is None:
        raw_jobs = [payload]  # backward compat (single job)
    logging.info("config_handler: number of incoming jobs: %d", len(raw_jobs))

    attributes = ["video", "audio", "browsing", "cloud", "download", "game", "map", "RTT"]  # Need to get from agent
    domains_by_attribute = _get_domains_by_attribute(attributes)

    # ---------- parse & validate and expand jobs ----------
    all_expanded_jobs = []
    all_errors = []

    for attribute_name, domain_list in domains_by_attribute.items():
        if isinstance(domain_list, str): # Handle error case from domain_maintainer
            logging.warning(f"Skipping attribute '{attribute_name}' due to error: {domain_list}")
            all_errors.append({"index": -1, "error": f"Attribute '{attribute_name}' error: {domain_list}"})
            continue

        for specific_domain in domain_list:
            for idx, j in enumerate(raw_jobs):
                os_raw = pick(j, "operationSystem", "os")
                browser = norm_browser(pick(j, "browser"))
                algo_name = norm_algo(pick(j, "algorithm", "algo"))
                sessions_raw = pick(j, "sessions", "session", "count")

                logging.debug("job[%d] raw -> os=%r browser=%r algo=%r sessions=%r",
                              idx, os_raw, browser, algo_name, sessions_raw)

                try:
                    opsys = norm_os(os_raw)
                    if isinstance(sessions_raw, str):
                        sessions_raw = sessions_raw.strip()
                    if sessions_raw is None or (isinstance(sessions_raw, str) and not sessions_raw.isdigit()):
                        raise ValueError("sessions must be an integer > 0")
                    sessions = int(sessions_raw)
                except Exception as e:
                    logging.warning("job[%d] parse error: %s", idx, e)
                    all_errors.append({"index": idx, "error": f"Bad job: {e}"})
                    continue

                # validate
                if opsys not in {"linux", "windows", "macos"}:
                    all_errors.append({"index": idx, "error": "Invalid operating system"});
                    continue
                if browser not in {"chrome", "firefox"}:
                    all_errors.append({"index": idx, "error": "Invalid web browser"});
                    continue
                if algo_name not in {"kyber", "mlkem", "non-pqc"}:
                    all_errors.append({"index": idx, "error": "Invalid algorithm"});
                    continue
                if sessions <= 0:
                    all_errors.append({"index": idx, "error": "Invalid sessions"});
                    continue

                try:
                    target_key = choose_container(opsys, algo_name)
                    target_base = Containers[target_key].rstrip("/")
                    algo_code = ALGO_NAME_TO_CODE[algo_name.lower()]  # int 0/1/2
                except Exception as e:
                    all_errors.append({"index": idx, "error": str(e)})
                    continue

                # This is the job that will be passed to run_one
                all_expanded_jobs.append({
                    "original_raw_job_idx": idx, # Keep track of original raw_job index for results
                    "opsys": opsys,
                    "browser": browser,
                    "algo_name": algo_name,  # str ("kyber"/"mlkem"/"non-pqc")
                    "algo_code": algo_code,  # int (1/2/0)
                    "sessions": sessions,  # sniffer manages N internally
                    "target_key": target_key,
                    "target_base": target_base,
                    "domain": specific_domain,
                    "attribute": attribute_name
                })

    if not all_expanded_jobs:
        out = {"error": "No valid jobs to process", "detail": all_errors}
        logging.error("config_handler: no valid jobs to process. errors=%s", all_errors)
        return Response(json.dumps(out, indent=2, ensure_ascii=False),
                        status=400, mimetype="application/json")

    logging.info("config_handler: %d valid job(s) after parsing and domain expansion", len(all_expanded_jobs))

    # ---------- fan-out (serialized per-backend, parallel across backends) ----------
    # The results array needs to match the number of *expanded* jobs
    results = [None] * len(all_expanded_jobs)
    futures = {_EXECUTOR.submit(run_one, jb, jb["domain"], jb["attribute"]): jb for jb in all_expanded_jobs}

    # Aggregate results based on the order of all_expanded_jobs
    for i, fut in enumerate(as_completed(futures)):
        jb = futures[fut]
        try:
            results[i] = fut.result()
        except Exception as e:
            logging.exception("job[%d] run_one crashed: %s", jb["original_raw_job_idx"], e)
            results[i] = {
                "routed_to": jb["target_key"],
                "backend": {"execute": {"status": 500, "response": {"error": str(e)}}},
                "sniffer": {}
            }

    # If there were any parsing/validation errors for original raw_jobs, they should be included.
    # For minimal change, we'll just append them to the results list if they exist.
    # A more robust solution might involve grouping results by original_raw_job_idx.
    if all_errors:
        results.extend(all_errors)

    body = {
        "backends": results,
        "note": "One sniffer /start per job (session_count=N). Early-stop when qualified_reached=true → call /done; otherwise poll until done or timeout."
    }

    pretty = json.dumps(body, indent=2, ensure_ascii=False)
    logging.info("config_handler: returning 207 with multi-status body")
    return Response(pretty, status=207, mimetype="application/json")


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


def _get_domains_by_attribute(attributes: List[str], base_url: str =
"http://domain_maintainer:5010") -> Dict[str, Union[List[str], str]]:
    """
    Fetches domains for a given list of attributes by making a GET request
    to the domain_maintainer service.

    Args:
        attributes: A list of attributes (e.g., ['video', 'audio']).
        base_url: The base URL of the domain_maintainer service.

    Returns:
        A dictionary where keys are attributes and values are the corresponding
        lists of domains. Returns an empty dictionary if an error occurs.
        Example:
        {
            "video": ["youtube.com", "vimeo.com"],
            "news": ["cnn.com", "bbc.com"],
            "invalid_attr": "Error reading sheet: Sheet 'invalid_attr' not found"
        }
    """
    if not attributes:
        return {}

    # The endpoint expects multiple 'attributes' query parameters
    params = [("attributes", attr) for attr in attributes]
    endpoint = f"{base_url}/get_domains/"

    try:
        # Send the GET request
        response = requests.get(endpoint, params=params)

        # Raise an exception for bad status codes (4xx or 5xx)
        response.raise_for_status()

        # The JSON response is already in the desired format
        # e.g., {"video": ["youtube.com", ...], "news": ["cnn.com", ...]}
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"Error fetching domains: {e}")
        return {}
    except ValueError:  # Catches JSON decoding errors
        print("Error: Failed to decode JSON response from the server.")
        return {}


# ---------- helpers ----------
def pick(d, *keys):
    """return first present non-None key from d."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def norm_os(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    return OS_MAP.get(s, s)  # "0"->"linux" etc., or pass-through


def norm_algo(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in {"nopqc", "no-pqc"}:
        s = "non-pqc"
    return ALGO_MAP.get(s, s)  # "1"->"kyber" etc., or pass-through


def norm_browser(v):
    if v is None:
        return None
    return str(v).strip().lower()


# ---------- per-job runner ----------
def run_one(jb, domain, attribute):
    """
    For a single job:
      1) sniffer /start (session_count = jb['sessions'])
      2) backend /execute
      3) poll sniffer /status; if 'qualified_reached' → proactively call /done
      4) in any case, call sniffer /done (idempotent) at the end, with all session_ids
    """
    logging.debug(f"Starting job with domain: {domain} and attribute: {attribute}")
    poll_interval = float(os.getenv("SNIFFER_POLL_INTERVAL_SEC", "5"))
    per_session = float(os.getenv("SNIFFER_WAIT_PER_SESSION", "30"))
    max_wait = per_session * max(1, jb["sessions"])
    max_wait_cap = float(os.getenv("SNIFFER_MAX_TOTAL_WAIT_SEC", "10800"))  # 3h default
    if max_wait > max_wait_cap:
        logging.warning("Capping max_wait from %.0fs to %.0fs", max_wait, max_wait_cap)
        max_wait = max_wait_cap

    stop_on_sender_done = os.getenv("SWITCHER_STOP_ON_SENDER_DONE", "true").lower() in {"1", "true", "yes"}
    sender_done_grace = float(
        os.getenv("SENDER_DONE_GRACE_SEC", "2.0"))  # to capture last ch/sh, maybe switch to sleep?

    logging.info("job[%d] routed_to=%s | wait plan: sessions=%d, per_session=%ss -> max_wait=%ss",
                 jb["original_raw_job_idx"], jb["target_key"], jb["sessions"], per_session, max_wait)

    sem = _backend_slots[jb["target_key"]]
    with sem:
        backend_ip = _resolve_service_ip(jb["target_base"])
        logging.info("job[%d] backend ip resolved: %s", jb["original_raw_job_idx"], backend_ip)

        # 1) sniffer /start (session_count=N)
        start_target = {
            "os": jb["opsys"],
            "browser": jb["browser"],
            "algo": jb["algo_code"],
            "container_ip": backend_ip,
            "duration_sec": max_wait,  # upper bound; we may stop early
            "filter_mode": SNIFFER_FILTER_MODE,
            "domain": domain if SNIFFER_FILTER_MODE == "domain" else None,
            "session_count": jb["sessions"],
        }
        for k in list(start_target.keys()):
            if start_target[k] is None:
                del start_target[k]

        sn_start = {"status": None, "response": None}
        child_ids = []
        try:
            logging.info("job[%d] sniffer /start -> %s", jb["original_raw_job_idx"], SNIFFER_URL)
            s = requests.post(f"{SNIFFER_URL}/start", json={"targets": [start_target]}, timeout=30)
            sn_start["status"] = s.status_code
            try:
                sb = s.json()
            except ValueError:
                sb = {"text": s.text}
            sn_start["response"] = sb

            children = []
            if isinstance(sb, dict):
                if "children" in sb and isinstance(sb["children"], list):
                    children = sb["children"]
                elif "response" in sb and isinstance(sb["response"], dict) and "children" in sb["response"]:
                    children = sb["response"]["children"] or []
            for ch in children:
                sid = ch.get("session_id")
                if sid:
                    child_ids.append(sid)
            logging.info("job[%d] sniffer started; session_ids=%s", jb["original_raw_job_idx"], child_ids)
        except requests.RequestException as e:
            logging.critical("job[%d] sniffer /start unreachable: %s", jb["original_raw_job_idx"], e)
            sn_start = {"status": 502, "response": {"error": f"sniffer /start unreachable: {e}"}}

        time.sleep(0.5)  # tiny arm wait

        # 2) backend /execute (SENDER)
        exec_url = f'{jb["target_base"]}{TARGET_ENDPOINT}'
        exec_payload = {
            "os": jb["opsys"],
            "browser": jb["browser"],
            "algorithm": jb["algo_code"],  # INT 0/1/2 expected by sender
            "sessions": jb["sessions"],
            "domain": domain,
            "attribute": attribute,
        }
        backend_exec = {"status": None, "response": None}
        sender_says_done = False
        try:
            logging.info("job[%d] backend /execute -> %s | payload=%s", jb["original_raw_job_idx"], exec_url, exec_payload)
            r = requests.post(exec_url, json=exec_payload, timeout=None)  # let sender run to completion
            backend_exec["status"] = r.status_code
            try:
                backend_exec["response"] = r.json()
            except ValueError:
                backend_exec["response"] = {"text": r.text}
            logging.info("job[%d] backend /execute returned %s", jb["original_raw_job_idx"], r.status_code)

            # ---- NEW: Stop-on-sender-done path ----
            if stop_on_sender_done and r.ok:
                body = backend_exec["response"] or {}
                if isinstance(body, dict) and body.get("status") == "done":
                    sender_says_done = True
                    logging.info("job[%d] sender reports status=done; stopping sniffer now", jb["original_raw_job_idx"])
        except requests.RequestException as e:
            logging.error("job[%d] backend unreachable: %s", jb["original_raw_job_idx"], e)
            backend_exec = {"status": 502, "response": {"error": f"backend unreachable: {e}"}}

        start_ts = time.time()
        finished = False
        sn_status_samples = []

        # 3a) If sender said done -> stop sniffer immediately
        if sender_says_done:
            if sender_done_grace > 0:
                time.sleep(sender_done_grace)  # tiny grace to let last packets flush

            sn_done = {"status": None, "response": None}
            done_payload = {"container_ip": backend_ip}
            if child_ids:
                done_payload["session_ids"] = child_ids
            try:
                logging.info("job[%d] sniffer /done (sender_done) -> %s | payload=%s",
                             jb["original_raw_job_idx"], SNIFFER_URL, done_payload)
                d = requests.post(f"{SNIFFER_URL}/done", json=done_payload, timeout=20)
                try:
                    d_body = d.json()
                except ValueError:
                    d_body = {"text": d.text}
                sn_done = {"status": d.status_code, "response": d_body}
                logging.info("job[%d] sniffer /done returned %s", jb["original_raw_job_idx"], d.status_code)
            except requests.RequestException as e:
                logging.error("job[%d] sniffer /done unreachable: %s", jb["original_raw_job_idx"], e)
                sn_done = {"status": 502, "response": {"error": f"sniffer /done unreachable: {e}"}}

            finished = True  # we intentionally stopped
            return {
                "routed_to": jb["target_key"],
                "backend": {"execute": backend_exec},
                "sniffer": {
                    "start": sn_start,
                    "wait": {
                        "polled": False,
                        "interval_sec": poll_interval,
                        "max_wait_sec": max_wait,
                        "elapsed_sec": round(time.time() - start_ts, 2),
                        "finished": finished,
                        "samples": sn_status_samples,
                        "reason": "sender_done",
                    },
                    "done": sn_done,
                }
            }

        logging.info("job[%d] polling sniffer /status every %ss up to %ss",
                     jb["original_raw_job_idx"], poll_interval, max_wait)

        while time.time() - start_ts < max_wait:
            try:
                st = requests.get(f"{SNIFFER_URL}/status", timeout=5)
                body = st.json() if st.ok else {"error": f"status {st.status_code}"}
            except Exception as e:
                body = {"error": f"status unreachable: {e}"}

            if len(sn_status_samples) < 4:
                sn_status_samples.append(body)

            if isinstance(body, dict) and all_done(body, child_ids):
                finished = True
                logging.info("job[%d] sniffer reports this run's session_ids are done", jb["original_raw_job_idx"])
                break

            time.sleep(poll_interval)

        # 4) /done (idempotent) after polling window
        sn_done = {"status": None, "response": None}
        done_payload = {"container_ip": backend_ip}
        if child_ids:
            done_payload["session_ids"] = child_ids
        try:
            logging.info("job[%d] sniffer /done -> %s | payload=%s",
                         jb["original_raw_job_idx"], SNIFFER_URL, done_payload)
            d = requests.post(f"{SNIFFER_URL}/done", json=done_payload, timeout=20)
            try:
                d_body = d.json()
            except ValueError:
                d_body = {"text": d.text}
            sn_done = {"status": d.status_code, "response": d_body}
            logging.info("job[%d] sniffer /done returned %s", jb["original_raw_job_idx"], d.status_code)
        except requests.RequestException as e:
            logging.error("job[%d] sniffer /done unreachable: %s", jb["original_raw_job_idx"], e)
            sn_done = {"status": 502, "response": {"error": f"sniffer /done unreachable: {e}"}}

        return {
            "routed_to": jb["target_key"],
            "backend": {"execute": backend_exec},
            "sniffer": {
                "start": sn_start,
                "wait": {
                    "polled": True,
                    "interval_sec": poll_interval,
                    "max_wait_sec": max_wait,
                    "elapsed_sec": round(time.time() - start_ts, 2),
                    "finished": finished,
                    "samples": sn_status_samples,
                },
                "done": sn_done,
            }
        }


def all_done(body: dict, child_ids: list[str]) -> bool:
    sessions = {s.get("session_id"): s for s in body.get("sessions", [])}
    for sid in child_ids:
        s = sessions.get(sid)
        if not s:
            return False
        if not (s.get("qualified_reached") or s.get("done")):
            return False
    return True


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
