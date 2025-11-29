import json
import logging
import os
import socket
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from threading import Semaphore
from urllib.parse import urlparse

import requests
from flask import Flask, json
from flask import Response, request

# one-at-a-time per backend key
_backend_slots = defaultdict(lambda: Semaphore(1))
# modest concurrency across different backends
_EXECUTOR = ThreadPoolExecutor(max_workers=10)

# Sniffer config (env-driven)
SNIFFER_URL = os.getenv("SNIFFER_URL", "http://172.18.0.1:8080")
SNIFFER_FILTER_MODE = "domain"

# Internal mapping for the sniffer API (which still expects integers)
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

# ==========================
# Generic helper functions
# ==========================

def get_first_present_value(mapping: dict, *keys):
    """
    Return the first key from `keys` that exists in `mapping` and is not None.
    If no such key exists, return None.
    """
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def normalize_operating_system(raw_value):
    """
    Normalize OS name. Must be a string (case-insensitive).
    """
    if raw_value is None:
        return None
    return str(raw_value).strip().lower()


def normalize_algorithm_name(raw_value):
    """
    Normalize algorithm name. Must be a string (case-insensitive).
    """
    if raw_value is None:
        return None
    return str(raw_value).strip().lower()


def normalize_browser_name(raw_value):
    """
    Normalize browser name (chrome/firefox).
    """
    if raw_value is None:
        return None
    return str(raw_value).strip().lower()


def compute_sniffer_wait_plan(session_count: int):
    """
    Compute polling interval and maximum wait time for the sniffer.
    """
    poll_interval_seconds = float(os.getenv("SNIFFER_POLL_INTERVAL_SEC", "10"))
    wait_per_session_seconds = float(os.getenv("SNIFFER_WAIT_PER_SESSION", "30"))
    maximum_wait_seconds = wait_per_session_seconds * max(1, session_count)

    return poll_interval_seconds, maximum_wait_seconds


def get_sender_behavior_config():
    """
    Read configuration flags that control how we react to sender 'done' status.
    """
    stop_on_sender_done_env = os.getenv("SWITCHER_STOP_ON_SENDER_DONE", "true")
    stop_on_sender_done = stop_on_sender_done_env.lower() in {"1", "true", "yes"}

    sender_done_grace_seconds = float(os.getenv("SENDER_DONE_GRACE_SEC", "2.0"))

    return stop_on_sender_done, sender_done_grace_seconds


# =======================================
# Job parsing and validation from payload
# =======================================

def parse_jobs_from_payload(request_payload: dict):
    """
    Parse and validate jobs from incoming payload.

    Returns:
        raw_job_payloads: list[dict] - raw job list (for aligning indices)
        valid_jobs: list[dict] - normalized jobs ready to run
        parse_errors: list[dict] - parse/validation errors with indices
    """
    raw_job_payloads = request_payload.get("jobs")
    if raw_job_payloads is None:
        # Backward compatibility: single-job payload
        raw_job_payloads = [request_payload]

    logging.info("config_handler: number of incoming jobs: %d", len(raw_job_payloads))

    valid_jobs = []
    parse_errors = []

    for job_index, job_payload in enumerate(raw_job_payloads):
        raw_os_value = get_first_present_value(job_payload, "operationSystem", "os")
        raw_browser_value = get_first_present_value(job_payload, "browser", "web")
        raw_algorithm_value = get_first_present_value(job_payload, "algorithm", "algo")
        raw_sessions_value = get_first_present_value(job_payload, "sessions", "session", "count")

        browser_name = normalize_browser_name(raw_browser_value)
        algorithm_name = normalize_algorithm_name(raw_algorithm_value)
        operating_system = normalize_operating_system(raw_os_value)

        logging.debug(
            "job[%d] raw -> os=%r browser=%r algo=%r sessions=%r",
            job_index,
            raw_os_value,
            browser_name,
            algorithm_name,
            raw_sessions_value,
        )

        try:
            if isinstance(raw_sessions_value, str):
                raw_sessions_value = raw_sessions_value.strip()
            if raw_sessions_value is None or (isinstance(raw_sessions_value, str) and not raw_sessions_value.isdigit()):
                raise ValueError("sessions must be an integer > 0")

            session_count = int(raw_sessions_value)

        except Exception as parse_exception:
            logging.warning("job[%d] parse error: %s", job_index, parse_exception)
            parse_errors.append({"index": job_index, "error": f"Bad job: {parse_exception}"})
            continue

        # Validation
        if operating_system not in {"linux", "windows", "macos"}:
            parse_errors.append({"index": job_index, "error": "Invalid operating system. Must be 'linux', 'windows', or 'macos'."})
            continue

        if browser_name not in {"chrome", "firefox"}:
            parse_errors.append({"index": job_index, "error": "Invalid web browser. Must be 'chrome' or 'firefox'."})
            continue

        if algorithm_name not in {"kyber", "mlkem", "non-pqc"}:
            parse_errors.append({"index": job_index, "error": "Invalid algorithm. Must be 'non-pqc', 'kyber', or 'mlkem'."})
            continue

        if session_count <= 0:
            parse_errors.append({"index": job_index, "error": "Invalid sessions"})
            continue

        try:
            target_container_key = choose_container(operating_system, algorithm_name)
            target_base_url = Containers[target_container_key].rstrip("/")
            algorithm_code = ALGO_NAME_TO_CODE[algorithm_name]  # int 0/1/2
        except Exception as container_exception:
            parse_errors.append({"index": job_index, "error": str(container_exception)})
            continue

        valid_jobs.append({
            "idx": job_index,
            "opsys": operating_system,
            "browser": browser_name,
            "algo_name": algorithm_name,
            "algo_code": algorithm_code,
            "sessions": session_count,
            "target_key": target_container_key,
            "target_base": target_base_url,
        })

    return raw_job_payloads, valid_jobs, parse_errors


# =======================
# Sniffer-related helpers
# =======================

def start_sniffer(job_definition: dict, backend_ip_address: str, maximum_wait_seconds: float):
    """
    Start the sniffer for a given job.

    Returns:
        sniffer_start_info: dict  - {status, response}
        session_ids: list[str]    - list of session_ids created by the sniffer
    """
    start_sniffer_payload = {
        "os": job_definition["opsys"],
        "browser": job_definition["browser"],
        "algorithm": job_definition["algo_name"],
        "container_ip": backend_ip_address,
        "duration_sec": maximum_wait_seconds,
        "domain": "pq.cloudflareresearch.com",
        "session": job_definition["sessions"],
    }

    # Remove None values
    start_sniffer_payload = {
        key: value
        for key, value in start_sniffer_payload.items()
        if value is not None
    }

    sniffer_start_info = {"status": None, "response": None}
    session_ids = []

    try:
        logging.info("job[%d] sniffer /start -> %s", job_definition["idx"], SNIFFER_URL)

        http_sniffer_start_response = requests.post(
            f"{SNIFFER_URL}/start",
            json={"targets": [start_sniffer_payload]},
            timeout=30,
        )

        sniffer_start_info["status"] = http_sniffer_start_response.status_code

        try:
            sniffer_start_body = http_sniffer_start_response.json()
        except ValueError:
            sniffer_start_body = {"text": http_sniffer_start_response.text}

        sniffer_start_info["response"] = sniffer_start_body

        children_entries = []
        if isinstance(sniffer_start_body, dict):
            if "children" in sniffer_start_body:
                children_entries = sniffer_start_body.get("children", [])
            elif "response" in sniffer_start_body and isinstance(
                    sniffer_start_body["response"], dict
            ):
                children_entries = sniffer_start_body["response"].get("children", []) or []

        for child_entry in children_entries:
            session_id = child_entry.get("session_id")
            if session_id:
                session_ids.append(session_id)

        logging.info(
            "job[%d] sniffer started; session_ids=%s",
            job_definition["idx"],
            session_ids,
        )

    except requests.RequestException as start_exception:
        logging.critical(
            "job[%d] sniffer /start unreachable: %s",
            job_definition["idx"],
            start_exception,
        )
        sniffer_start_info = {
            "status": 502,
            "response": {"error": f"sniffer /start unreachable: {start_exception}"},
        }

    return sniffer_start_info, session_ids


def all_sessions_for_job_are_done(status_body: dict, session_ids: list[str]) -> bool:
    """
    Helper to determine if all sessions belonging to this job are done.
    """
    sessions_by_id = {
        session_entry.get("session_id"): session_entry
        for session_entry in status_body.get("sessions", [])
    }

    for session_id in session_ids:
        session_entry = sessions_by_id.get(session_id)
        if not session_entry:
            return False
        if not (session_entry.get("qualified_reached") or session_entry.get("done")):
            return False

    return True


def poll_sniffer_until_done(
        job_definition: dict,
        session_ids: list[str],
        poll_interval_seconds: float,
        maximum_wait_seconds: float,
):
    """
    Poll sniffer /status until all session_ids are finished or timeout expires.

    Returns:
        finished: bool
        status_samples: list[dict]
        elapsed_seconds: float
    """
    logging.info(
        "job[%d] polling sniffer /status every %ss up to %ss",
        job_definition["idx"],
        poll_interval_seconds,
        maximum_wait_seconds,
    )

    poll_start_timestamp = time.time()
    sniffer_status_samples = []
    sniffer_finished = False

    while time.time() - poll_start_timestamp < maximum_wait_seconds:
        try:
            http_status_response = requests.get(
                f"{SNIFFER_URL}/status",
                timeout=5,
            )
            if http_status_response.ok:
                sniffer_status_body = http_status_response.json()
            else:
                sniffer_status_body = {
                    "error": f"status {http_status_response.status_code}"
                }
        except Exception as status_exception:
            sniffer_status_body = {"error": f"status unreachable: {status_exception}"}

        if len(sniffer_status_samples) < 4:
            sniffer_status_samples.append(sniffer_status_body)

        if isinstance(sniffer_status_body, dict) and all_sessions_for_job_are_done(
                sniffer_status_body, session_ids
        ):
            logging.info(
                "job[%d] sniffer reports this run's session_ids are done",
                job_definition["idx"],
            )
            sniffer_finished = True
            break

        time.sleep(poll_interval_seconds)

    elapsed_seconds = round(time.time() - poll_start_timestamp, 2)
    return sniffer_finished, sniffer_status_samples, elapsed_seconds


def stop_sniffer(job_definition: dict, backend_ip_address: str, session_ids: list[str]):
    """
    Call sniffer /done for this job (idempotent).
    Returns a dict: {status, response}.
    """
    sniffer_done_payload = {"container_ip": backend_ip_address}
    if session_ids:
        sniffer_done_payload["session_ids"] = session_ids

    sniffer_done_info = {"status": None, "response": None}

    try:
        logging.info(
            "job[%d] sniffer /done -> %s | payload=%s",
            job_definition["idx"],
            SNIFFER_URL,
            sniffer_done_payload,
        )

        http_done_response = requests.post(
            f"{SNIFFER_URL}/done",
            json=sniffer_done_payload,
            timeout=20,
        )

        try:
            sniffer_done_body = http_done_response.json()
        except ValueError:
            sniffer_done_body = {"text": http_done_response.text}

        sniffer_done_info["status"] = http_done_response.status_code
        sniffer_done_info["response"] = sniffer_done_body

        logging.info(
            "job[%d] sniffer /done returned %s",
            job_definition["idx"],
            http_done_response.status_code,
        )

    except requests.RequestException as done_exception:
        logging.error(
            "job[%d] sniffer /done unreachable: %s",
            job_definition["idx"],
            done_exception,
        )
        sniffer_done_info = {
            "status": 502,
            "response": {"error": f"sniffer /done unreachable: {done_exception}"},
        }

    return sniffer_done_info


# ==========================
# Sender-related helpers
# ==========================

def execute_sender(job_definition: dict):
    """
    Call backend /execute for the given job.

    Returns:
        sender_execute_info: dict - {status, response}
    """
    execute_url = f'{job_definition["target_base"]}{TARGET_ENDPOINT}'
    execute_payload = {
        "os": job_definition["opsys"],
        "browser": job_definition["browser"],
        "algorithm": job_definition["algo_code"],  # INT 0/1/2 expected by sender
        "sessions": job_definition["sessions"],
    }

    sender_execute_info = {"status": None, "response": None}

    try:
        logging.info(
            "job[%d] backend /execute -> %s | payload=%s",
            job_definition["idx"],
            execute_url,
            execute_payload,
        )

        http_execute_response = requests.post(
            execute_url,
            json=execute_payload,
            timeout=None,  # let sender run to completion
        )
        sender_execute_info["status"] = http_execute_response.status_code

        try:
            sender_execute_info["response"] = http_execute_response.json()
        except ValueError:
            # Fallback to raw text body
            sender_execute_info["response"] = {"text": http_execute_response.text}

        logging.info(
            "job[%d] backend /execute returned %s",
            job_definition["idx"],
            http_execute_response.status_code,
        )

    except requests.RequestException as execute_exception:
        logging.error(
            "job[%d] backend unreachable: %s",
            job_definition["idx"],
            execute_exception,
        )
        sender_execute_info = {
            "status": 502,
            "response": {"error": f"backend unreachable: {execute_exception}"},
        }

    return sender_execute_info


def sender_reports_done(sender_execute_info: dict, stop_on_sender_done: bool) -> bool:
    """
    Decide whether the sender reports 'done' in a way that should stop sniffer early.
    """
    if not stop_on_sender_done:
        return False

    status_code = sender_execute_info.get("status")
    if status_code is None or status_code >= 400:
        return False

    response_body = sender_execute_info.get("response") or {}
    if isinstance(response_body, dict) and response_body.get("status") == "done":
        return True

    return False


# =======================
# Per-job orchestration
# =======================

def run_single_job(job_definition: dict):
    """
    Orchestrate sniffer + sender for a single job.

    Steps:
      1. Resolve backend IP and acquire slot semaphore.
      2. Start sniffer (/start).
      3. Run sender (/execute).
      4a. If sender reports 'done' and config allows -> stop sniffer immediately.
      4b. Otherwise, poll sniffer /status and then stop (/done).
    """
    poll_interval_seconds, maximum_wait_seconds = compute_sniffer_wait_plan(
        job_definition["sessions"]
    )
    stop_on_sender_done, sender_done_grace_seconds = get_sender_behavior_config()

    logging.info(
        "job[%d] routed_to=%s | wait plan: sessions=%d -> max_wait=%ss",
        job_definition["idx"],
        job_definition["target_key"],
        job_definition["sessions"],
        maximum_wait_seconds,
    )

    backend_semaphore = _backend_slots[job_definition["target_key"]]

    with backend_semaphore:
        backend_ip_address = resolve_service_ip(job_definition["target_base"])
        logging.info(
            "job[%d] backend ip resolved: %s",
            job_definition["idx"],
            backend_ip_address,
        )

        # Start sniffer
        sniffer_start_info, session_ids = start_sniffer(
            job_definition,
            backend_ip_address,
            maximum_wait_seconds,
        )
        time.sleep(0.5)  # tiny wait to arm sniffer

        # Run sender
        sender_execute_info = execute_sender(job_definition)

        # Early-stop path if sender says 'done'
        if sender_reports_done(sender_execute_info, stop_on_sender_done):
            logging.info(
                "job[%d] sender reports status=done; stopping sniffer now",
                job_definition["idx"],
            )

            # tiny arm
            if sender_done_grace_seconds > 0:
                time.sleep(sender_done_grace_seconds)

            sniffer_done_info = stop_sniffer(
                job_definition,
                backend_ip_address,
                session_ids,
            )

            elapsed_seconds = 0.0  # trivial; not polling in this path
            return {
                "routed_to": job_definition["target_key"],
                "backend": {"execute": sender_execute_info},
                "sniffer": {
                    "start": sniffer_start_info,
                    "wait": {
                        "polled": False,
                        "interval_sec": poll_interval_seconds,
                        "max_wait_sec": maximum_wait_seconds,
                        "elapsed_sec": elapsed_seconds,
                        "finished": True,
                        "samples": [],
                        "reason": "sender_done",
                    },
                    "done": sniffer_done_info,
                },
            }

        # Legacy polling path
        sniffer_finished, sniffer_status_samples, elapsed_seconds = poll_sniffer_until_done(
            job_definition,
            session_ids,
            poll_interval_seconds,
            maximum_wait_seconds,
        )

        # Always call sniffer /done at the end (idempotent)
        sniffer_done_info = stop_sniffer(
            job_definition,
            backend_ip_address,
            session_ids,
        )

        return {
            "routed_to": job_definition["target_key"],
            "backend": {"execute": sender_execute_info},
            "sniffer": {
                "start": sniffer_start_info,
                "wait": {
                    "polled": True,
                    "interval_sec": poll_interval_seconds,
                    "max_wait_sec": maximum_wait_seconds,
                    "elapsed_sec": elapsed_seconds,
                    "finished": sniffer_finished,
                    "samples": sniffer_status_samples,
                },
                "done": sniffer_done_info,
            },
        }


# =======================
# Flask route: /config
# =======================

@app.route("/config", methods=["POST"])
def config_handler():
    request_payload = request.get_json(silent=True) or {}
    logging.info("config_handler: received payload: %s", request_payload)

    raw_job_payloads, valid_jobs, parse_errors = parse_jobs_from_payload(request_payload)

    if not valid_jobs:
        error_body = {"error": "No valid jobs", "detail": parse_errors}
        logging.error("config_handler: no valid jobs. errors=%s", parse_errors)
        return Response(
            json.dumps(error_body, indent=2, ensure_ascii=False),
            status=400,
            mimetype="application/json",
        )

    logging.info(
        "config_handler: %d valid job(s) after parsing",
        len(valid_jobs),
    )

    # Fan-out (serialized per backend via semaphore, but parallel across backends)
    result_entries = [None] * len(raw_job_payloads)
    future_to_job = {
        _EXECUTOR.submit(run_single_job, job_definition): job_definition
        for job_definition in valid_jobs
    }

    for executor_future in as_completed(future_to_job):
        job_definition = future_to_job[executor_future]
        job_index = job_definition["idx"]

        try:
            result_entries[job_index] = executor_future.result()
        except Exception as job_exception:
            logging.exception(
                "job[%d] run_single_job crashed: %s",
                job_index,
                job_exception,
            )
            result_entries[job_index] = {
                "routed_to": job_definition["target_key"],
                "backend": {
                    "execute": {
                        "status": 500,
                        "response": {"error": str(job_exception)},
                    }
                },
                "sniffer": {},
            }

    # Include parse/validation errors at their indices
    for error_entry in parse_errors:
        error_index = error_entry["index"]
        if error_index >= len(result_entries):
            result_entries.extend(
                [None] * (error_index - len(result_entries) + 1)
            )

        result_entries[error_index] = {
            "status": 400,
            "response": error_entry,
            "routed_to": None,
        }

    response_body = {
        "backends": result_entries,
        "note": (
            "One sniffer /start per job (session_count=N). "
            "Early-stop when sender container finished sending requests or timeout."
        ),
    }

    pretty_response = json.dumps(response_body, indent=2, ensure_ascii=False)
    logging.info("config_handler: returning 207 with multi-status body")
    return Response(pretty_response, status=207, mimetype="application/json")


def resolve_service_ip(service_url: str) -> str:
    """
    Extract hostname from 'http://<host>:port' and DNS-resolve it to an IP
    from inside the Docker network (e.g., 172.19.0.x).
    """
    host = urlparse(service_url).hostname
    if not host:
        raise ValueError(f"Invalid service URL: {service_url}")
    return socket.gethostbyname(host)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)