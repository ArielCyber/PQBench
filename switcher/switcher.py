import json
import logging
import os
import socket
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore
from urllib.parse import urlparse

import requests
from flask import Flask, request, json
from flask import Response

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

    # ---------- parse & validate ----------
    jobs, errors = [], []
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
            target_key = choose_container(opsys, algo_name)
            target_base = Containers[target_key].rstrip("/")
            algo_code = ALGO_NAME_TO_CODE[algo_name.lower()]  # int 0/1/2
        except Exception as e:
            errors.append({"index": idx, "error": str(e)})
            continue

        jobs.append({
            "idx": idx,
            "opsys": opsys,
            "browser": browser,
            "algo_name": algo_name,  # str ("kyber"/"mlkem"/"non-pqc")
            "algo_code": algo_code,  # int (1/2/0)
            "sessions": sessions,  # sniffer manages N internally
            "target_key": target_key,
            "target_base": target_base
        })

    if not jobs:
        out = {"error": "No valid jobs", "detail": errors}
        logging.error("config_handler: no valid jobs. errors=%s", errors)
        return Response(json.dumps(out, indent=2, ensure_ascii=False),
                        status=400, mimetype="application/json")

    logging.info("config_handler: %d valid job(s) after parsing", len(jobs))

    # ---------- per-job runner ----------
    def run_one(jb):
        """
        For a single job:
          1) sniffer /start (session_count = jb['sessions'])
          2) backend /execute
          3) poll sniffer /status; if 'qualified_reached' → proactively call /done
          4) in any case, call sniffer /done (idempotent) at the end, with all session_ids
        """
        poll_interval = float(os.getenv("SNIFFER_POLL_INTERVAL_SEC", "5"))  # seconds
        per_session = float(os.getenv("SNIFFER_WAIT_PER_SESSION", "30"))  # seconds per session
        # Hard cap (env) to avoid unbounded waits; default 3 hours
        max_cap = float(os.getenv("SNIFFER_MAX_WAIT_CAP", "10800"))
        max_wait = min(per_session * max(1, jb["sessions"]), max_cap)

        if per_session * max(1, jb["sessions"]) > max_cap:
            logging.warning(
                "job[%d] planned wait %ss exceeds cap %ss; capping.",
                jb["idx"], per_session * max(1, jb["sessions"]), max_cap
            )

        logging.info(
            "job[%d] routed_to=%s | wait plan: sessions=%d, per_session=%ss -> max_wait=%ss (cap=%ss)",
            jb["idx"], jb["target_key"], jb["sessions"], per_session, max_wait, max_cap
        )

        sem = _backend_slots[jb["target_key"]]
        with sem:
            # resolve backend container IP for targeting the sniffer BPF
            backend_ip = _resolve_service_ip(jb["target_base"])
            logging.info("job[%d] backend ip resolved: %s", jb["idx"], backend_ip)

            # 1) sniffer /start
            start_target = {
                "os": jb["opsys"],
                "browser": jb["browser"],
                "algo": jb["algo_code"],
                "container_ip": backend_ip,
                "duration_sec": max_wait,  # an upper bound; monitor should stop earlier
                "iface": SNIFFER_IFACE,
                "filter_mode": SNIFFER_FILTER_MODE,
                "domain": SNIFFER_DOMAIN if SNIFFER_FILTER_MODE == "domain" else None,
                "ports": SNIFFER_PORTS,
                "session_count": jb["sessions"],
            }
            # strip None fields
            for k in list(start_target.keys()):
                if start_target[k] is None:
                    del start_target[k]

            sn_start = {"status": None, "response": None}
            child_ids = []
            try:
                logging.info("job[%d] sniffer /start -> %s", jb["idx"], SNIFFER_URL)
                s = requests.post(f"{SNIFFER_URL}/start", json={"targets": [start_target]}, timeout=30)
                sn_start["status"] = s.status_code
                try:
                    sb = s.json()
                except ValueError:
                    sb = {"text": s.text}
                sn_start["response"] = sb

                # extract session_ids for THIS run
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
                logging.info("job[%d] sniffer started; session_ids=%s", jb["idx"], child_ids)
            except requests.RequestException as e:
                logging.critical("job[%d] sniffer /start unreachable: %s", jb["idx"], e)
                sn_start = {"status": 502, "response": {"error": f"sniffer /start unreachable: {e}"}}

            # tiny arm wait
            time.sleep(0.5)

            # 2) backend /execute
            exec_url = f'{jb["target_base"]}{TARGET_ENDPOINT}'
            exec_payload = {
                "os": jb["opsys"],
                "browser": jb["browser"],
                "algorithm": jb["algo_code"],  # INT 0/1/2 expected by sender
                "sessions": jb["sessions"],  # info for sender; sniffer owns counting
            }
            backend_exec = {"status": None, "response": None}
            try:
                logging.info("job[%d] backend /execute -> %s | payload=%s", jb["idx"], exec_url, exec_payload)
                # Give sender a tad more than sniffer's max_wait
                single_request = requests.post(exec_url, json=exec_payload, timeout=max_wait + 60)
                backend_exec["status"] = single_request.status_code
                try:
                    backend_exec["response"] = single_request.json()
                except ValueError:
                    backend_exec["response"] = {"text": single_request.text}
                logging.info("job[%d] backend /execute returned %s", jb["idx"], single_request.status_code)
            except requests.RequestException as e:
                logging.error("job[%d] backend unreachable: %s", jb["idx"], e)
                backend_exec = {"status": 502, "response": {"error": f"backend unreachable: {e}"}}

            # 3) POLL sniffer /status with early-stop on qualified_reached
            def reached_or_done(body: dict, child_ids: list[str]) -> str | None:
                """
                Returns:
                  "reached"  -> one of our sessions has qualified_reached==True
                  "done"     -> all our sessions are done==True (files written)
                  None       -> keep waiting
                """
                sessions = body.get("sessions", [])
                if not isinstance(sessions, list):
                    return None

                by_id = {s.get("session_id"): s for s in sessions if isinstance(s, dict)}

                if child_ids:
                    # Early stop when any of our session_ids reached target
                    for sid in child_ids:
                        s = by_id.get(sid)
                        if s and s.get("qualified_reached") is True:
                            return "reached"
                    # Done only when all of our session_ids are done
                    if all(by_id.get(sid, {}).get("done") is True for sid in child_ids):
                        return "done"
                    return None

                # Fallback: early stop if any session for this IP reached target
                reached = any(
                    s.get("container_ip") == backend_ip and s.get("qualified_reached") is True
                    for s in sessions
                )
                if reached:
                    return "reached"

                # Done when all sessions for this IP are done
                relevant = [s for s in sessions if s.get("container_ip") == backend_ip]
                if relevant and all(s.get("done") is True for s in relevant):
                    return "done"

                return None

            sn_status_samples = []
            start_ts = time.time()
            finished = False
            sn_done_called = False
            logging.info("job[%d] polling sniffer /status every %ss up to %ss",
                         jb["idx"], poll_interval, max_wait)

            while time.time() - start_ts < max_wait:
                try:
                    st = requests.get(f"{SNIFFER_URL}/status", timeout=5)
                    body = st.json() if st.ok else {"error": f"status {st.status_code}"}
                except Exception as e:
                    body = {"error": f"status unreachable: {e}"}

                # keep a few samples for debugging
                if len(sn_status_samples) < 6:
                    sn_status_samples.append(body)

                flag = reached_or_done(body, child_ids)  # "reached" | "done" | None
                if flag == "reached":
                    logging.info("job[%d] sniffer reached target sessions → issuing /done now", jb["idx"])
                    if not sn_done_called:
                        try:
                            done_payload = {"container_ip": backend_ip}
                            if child_ids:
                                # Ask the sniffer to close *just* these session ids
                                done_payload["session_ids"] = child_ids
                            d = requests.post(f"{SNIFFER_URL}/done", json=done_payload, timeout=20)
                            sn_done_called = True
                            logging.info("job[%d] sniffer /done responded status=%s",
                                         jb["idx"], getattr(d, "status_code", "?"))
                        except Exception as e:
                            logging.warning("job[%d] sniffer /done failed: %s", jb["idx"], e)
                    # Give it one more tick to flip `done`
                    time.sleep(poll_interval)
                    continue

                if flag == "done":
                    finished = True
                    logging.info("job[%d] sniffer session(s) report done", jb["idx"])
                    break

                time.sleep(poll_interval)

            # 4) /done (sniffer) always called (idempotent), targeting THIS run
            sn_done = {"status": None, "response": None}
            try:
                done_payload = {"container_ip": backend_ip}
                if child_ids:
                    done_payload["session_ids"] = child_ids
                logging.info("job[%d] final sniffer /done -> %s | payload=%s",
                             jb["idx"], SNIFFER_URL, done_payload)
                d = requests.post(f"{SNIFFER_URL}/done", json=done_payload, timeout=20)
                try:
                    d_body = d.json()
                except ValueError:
                    d_body = {"text": d.text}
                sn_done = {"status": d.status_code, "response": d_body}
                logging.info("job[%d] final sniffer /done returned %s", jb["idx"], d.status_code)
            except requests.RequestException as e:
                logging.error("job[%d] sniffer /done unreachable: %s", jb["idx"], e)
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

    # ---------- fan-out (serialized per-backend, parallel across backends) ----------
    results = [None] * len(raw_jobs)
    futures = {_EXECUTOR.submit(run_one, jb): jb for jb in jobs}
    for fut in as_completed(futures):
        jb = futures[fut]
        try:
            results[jb["idx"]] = fut.result()
        except Exception as e:
            logging.exception("job[%d] run_one crashed: %s", jb["idx"], e)
            results[jb["idx"]] = {
                "routed_to": jb["target_key"],
                "backend": {"execute": {"status": 500, "response": {"error": str(e)}}},
                "sniffer": {}
            }

    # include parse/validation errors at their indices
    for err in errors:
        i = err["index"]
        if i >= len(results):
            results.extend([None] * (i - len(results) + 1))
        results[i] = {"status": 400, "response": err, "routed_to": None}

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
