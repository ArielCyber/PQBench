import logging
import os
import socket
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Body
from scapy.all import AsyncSniffer, wrpcap, get_if_list  # uses libpcap under the hood
from sessions import *
from threading import Event
import json
from shutil import which

"""
PQBench Sniffer: FastAPI microservice for capturing PCAPs inside a container.

Exposes /start, /status, /ifaces, and /health endpoints. Uses Scapy (libpcap)
to capture packets, builds BPF filters from several modes (none/domain/cidr/
ranges/custom), can intersect with TCP ports, and optionally splits TCP streams
with tshark into per-stream PCAPs.
"""


# ---------- Lifespan: logs interfaces at startup ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    log.info("Startup: initializing sniffer service...")
    try:
        ifaces = get_if_list()
        log.debug(f"Visible interfaces at startup: {ifaces}")
    except Exception as e:
        log.exception(f"Failed to list interfaces at startup: {e}")

    yield  # --- app runs here --- everything before yield is on startup, everything after is on shutdown

    # --- shutdown ---
    try:
        with _lock:
            still_running = [sid for sid, cs in _sessions.items() if not cs.done]
        if still_running:
            log.warning("Shutdown with %d active sessions: %s", len(still_running), still_running)
            # If you added stop-events/handles, you could signal them here.
    except Exception as e:
        log.exception("Shutdown cleanup failed: %s", e)


app = FastAPI(title="PQBench Sniffer", version="0.1.2", lifespan=lifespan)

# --------- Logging ----------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

log = logging.getLogger("pqbench.sniffer")

# ---------- Config ----------
OUTPUT_ROOT = "/output"

# ---------- State ----------
_lock = threading.Lock()
_active = {"running": False, "started_at": None, "target_ip": None, "outfile": None}
# All child sessions keyed by session_id
_sessions: dict[str, ChildSession] = {}

# Track live sniffers and their stop signals
_sniffer_handles: dict[str, AsyncSniffer] = {}
_stop_events: dict[str, Event] = {}

# remember the most recent parent run (for convenience in /status)
_last_parent = {"session_dir": None, "children": []}


# ---------- Helpers ----------
def _resolve_domain_ips(hostname: str) -> tuple[list[str], list[str]]:
    """
    Resolve a domain to unique IPv4/IPv6 addresses.

    Parameters:
        hostname: The FQDN to resolve.
    Returns:
        A tuple ``(v4_list, v6_list)`` of unique IP strings.

    Notes:
        Resolution errors are logged and result in empty lists.
    """
    log.debug("_resolve_domain_ips(): resolving %r", hostname)
    v4s: List[str] = []
    v6s: List[str] = []
    try:
        infos = socket.getaddrinfo(hostname, None)
        log.debug("_resolve_domain_ips(): getaddrinfo returned %d records", len(infos))
        for family, _, _, _, sockaddr in infos:
            if family == socket.AF_INET:
                ip = sockaddr[0]
                if ip not in v4s:
                    v4s.append(ip)
            elif family == socket.AF_INET6:
                ip = sockaddr[0]
                if ip not in v6s:
                    v6s.append(ip)
        log.debug("_resolve_domain_ips(): v4=%s | v6=%s", v4s, v6s)
    except Exception as e:
        log.exception("_resolve_domain_ips(): failed to resolve %r: %s", hostname, e)
    return v4s, v6s


def _build_domain_bpf(container_ip: str, domain_v4: List[str], domain_v6: List[str]) -> str:
    """
    Build a bidirectional BPF limited to a container IP and a domain's IPs.

    Produces a filter of the form:
    ``(host <container_ip>) and ((ip and (...v4...)) or (ip6 and (...v6...)))``.

    Args:
        container_ip: Target container IP.
        domain_v4: IPv4 addresses resolved for the domain.
        domain_v6: IPv6 addresses resolved for the domain.

    Returns:
        A BPF string.

    Notes:
        If no IPs are provided, falls back to ``ip or ip6`` to avoid an empty filter.
    """
    log.debug("_build_domain_bpf(): container=%s v4=%s v6=%s", container_ip, domain_v4, domain_v6)
    v4_parts = [f"(dst host {ip} or src host {ip})" for ip in domain_v4]
    v6_parts = [f"(dst host {ip} or src host {ip})" for ip in domain_v6]

    v4_clause = f"(ip and ({' or '.join(v4_parts)}))" if v4_parts else ""
    v6_clause = f"(ip6 and ({' or '.join(v6_parts)}))" if v6_parts else ""
    clause = " or ".join([c for c in [v4_clause, v6_clause] if c])

    if not clause:
        log.warning("_build_domain_bpf(): empty domain IP set; falling back to (ip or ip6)")
        clause = "ip or ip6"

    bpf = f"(host {container_ip}) and ({clause})"
    log.debug("_build_domain_bpf(): BPF=%s", bpf)
    return bpf


def name_dir(os_name: str, browser: str, algo: int) -> str:
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

    os_name = os_name.lower()
    if os_name != "linux" and os_name != "windows" and os_name != "macos":
        log.error(f"name_dir invalid os: {os_name}")
        raise ValueError(f"Invalid input: {os_name}")

    browser = browser.lower()
    if browser != "firefox" and browser != "chrome":
        log.error(f"name_dir invalid browser: {browser}")
        raise ValueError(f"Invalid input: {browser}")

    algo_map = {0: "non-pqc", 1: "kyber", 2: "mlkem"}
    algo_name = algo_map.get(algo)
    if algo_name is None:
        log.error(f"name_dir invalid algo: {algo}")
        raise ValueError(f"Invalid input: {algo}")

    code = f"{os_name}_{browser}_{algo_name}"
    log.debug(f"name_dir -> os={os_name} browser={browser} algo={algo_name} => {code}")
    return code


def _and_ports(bpf: str, ports_csv: Optional[str]) -> str:
    """
    AND a TCP port clause with an existing BPF, if ports were supplied.

    Args:
        bpf: Base BPF string.
        ports_csv: Comma-separated TCP ports (e.g., ``"443,80"``).

    Returns:
        The combined BPF. If ``ports_csv`` is empty/invalid, returns the original ``bpf``.
    """
    if not ports_csv:
        return bpf
    ports = [p.strip() for p in ports_csv.split(",") if p.strip().isdigit()]
    if not ports:
        return bpf
    if len(ports) == 1:
        port_clause = f"(tcp port {ports[0]})"
    else:
        port_clause = "(" + " or ".join([f"(tcp port {p})" for p in ports]) + ")"
    return f"({bpf}) and {port_clause}"


def _split_streams_tshark(input_pcap: str, output_dir: str, dir_code, timestamp, *, min_packets: int = 30,
                          require_serverhello: bool = True, require_appdata: bool = False,
                          force_tls_port: str | None = "443", ):  # set None to skip decode-as
    """
    Split only the *meaningful* TLS TCP streams from a PCAP using tshark.

    Rules:
      - Stream must contain a ClientHello (tls.handshake.type==1)
      - If require_serverhello: must also contain a ServerHello (type==2)
      - Stream must have >= min_packets TCP frames
      - If require_appdata: must contain TLS application data (content_type==23)

    Outputs:
      <output_dir>/stream-<sid>.pcap for each kept stream
      <output_dir>/_streams_debug.json with selection reasons
    """

    try:
        log.info("Starting stream split for %s", input_pcap)
        os.makedirs(output_dir, exist_ok=True)
        # dbg is just a debug information accumulator — a dictionary that collects
        # all the reasoning about which streams were kept or dropped and why.
        dbg = {
            "input": input_pcap,
            "min_packets": min_packets,
            "require_serverhello": require_serverhello,
            "require_appdata": require_appdata,
            "force_tls_port": force_tls_port,
            "steps": [],
            "kept": [],
            "dropped": []
        }

        def step(name, **k):
            dbg["steps"].append({"name": name, **k})

        if which("tshark") is None:
            log.warning("tshark not found; skipping stream split")
            return

        decode = []
        if force_tls_port:
            decode = ["-d", f"tcp.port=={force_tls_port},ssl"]
            step("decode-as", args=decode)

        # Find all streams that contain a ClientHello (candidate set)
        cmd_ch = ["tshark", "-r", input_pcap, *decode,
                  "-Y", "tls.handshake.type==1",
                  "-T", "fields", "-e", "tcp.stream"]
        step("cmd_clienthellos", cmd=cmd_ch)
        out_ch = subprocess.check_output(cmd_ch, text=True)
        cand_streams = sorted({s for s in out_ch.splitlines() if s.strip().isdigit()})
        step("clienthello_streams", count=len(cand_streams), sample=cand_streams[:50])

        kept_ids: list[str] = []
        for sid in cand_streams:
            reasons = []

            # Must contain a ServerHello
            has_sh = True
            if require_serverhello:
                cmd_sh = ["tshark", "-r", input_pcap, *decode,
                          "-Y", f"tcp.stream=={sid} && tls.handshake.type==2",
                          "-c", "1"]
                rc_sh = subprocess.run(cmd_sh, check=False,
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL).returncode
                has_sh = (rc_sh == 0)
                if not has_sh:
                    reasons.append("no_serverhello")

            # Count TCP frames on the stream
            cmd_cnt = ["tshark", "-r", input_pcap,
                       "-Y", f"tcp.stream=={sid} && tcp",
                       "-T", "fields", "-e", "frame.number"]
            out_cnt = subprocess.check_output(cmd_cnt, text=True)
            pkt_count = sum(1 for ln in out_cnt.splitlines() if ln.strip())
            if pkt_count < min_packets:
                reasons.append(f"too_few_packets({pkt_count})")

            # Require TLS AppData frames
            has_app = True
            if require_appdata:
                cmd_app = ["tshark", "-r", input_pcap, *decode,
                           "-Y", f"tcp.stream=={sid} && tls.record.content_type==23",
                           "-c", "1"]
                rc_app = subprocess.run(cmd_app, check=False,
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL).returncode
                has_app = (rc_app == 0)
                if not has_app:
                    reasons.append("no_appdata")

            if has_sh and pkt_count >= min_packets and has_app:
                kept_ids.append(sid)
                dbg["kept"].append({"sid": sid, "pkt_count": pkt_count})
            else:
                dbg["dropped"].append({"sid": sid, "pkt_count": pkt_count, "reasons": reasons})

        # Extract kept streams
        index = 0
        for sid in kept_ids:
            basename = f"session-{dir_code}-{timestamp}-{index:02d}.pcap"  # <-- no leading slash
            stream_out = os.path.join(output_dir, basename)  # <-- proper join
            index += 1

            # extra safety: ensure parent exists (in case output_dir was changed upstream)
            os.makedirs(os.path.dirname(stream_out), exist_ok=True)

            cmd_extract = [
                "tshark", "-r", input_pcap,
                *(["-d", f"tcp.port=={force_tls_port},ssl"] if force_tls_port else []),
                "-w", stream_out,
                "-Y", f"tcp.stream=={sid}"
            ]
            log.debug("Extracting stream %s -> %s | cmd=%s", sid, stream_out, " ".join(cmd_extract))
            subprocess.run(cmd_extract, check=False)

        # Persist debug info
        with open(os.path.join(output_dir, "_streams_debug.json"), "w", encoding="utf-8") as f:
            json.dump(dbg, f, indent=2)

        log.info("Streams kept: %d | dropped: %d", len(kept_ids), len(dbg["dropped"]))

    except FileNotFoundError:
        log.warning("tshark not found; skipping stream split")
    except subprocess.CalledProcessError as e:
        log.error(f"tshark failed: {e}")
    except Exception as e:
        log.exception(f"Unexpected error during stream split: {e}")

    log.info("Completed stream split: kept=%d dropped=%d",
             len(dbg["kept"]), len(dbg["dropped"]))


def _resolve_ip_from_url(url: str) -> str:
    """
    Converts given URL to an IPv4 address.
    :param url: URL to resolve
    :return: IPv4 address
    """
    host = urlparse(url).hostname
    if not host:
        raise ValueError(f"Invalid url: {url}")
    return socket.gethostbyname(host)


def _capture_job(session_id: str, duration: int, timestamp, armed_evt: Event | None = None):
    """
    This function is responsible for capturing the network traffic
    defined by the child session's BPF,
    :param session_id: the session ID
    :param duration: the duration of the capture
    :param timestamp: the timestamp of the capture
    :param armed_evt: an Event or None
    :return: None
    """
    child_session = _sessions.get(session_id)
    if not child_session:
        return
    log.info(
        f"[{session_id}] Capture start: ip={child_session.container_ip} iface={child_session.iface} outfile={child_session.outfile}")
    log.debug(f"[{session_id}] BPF: {child_session.bpf}")
    stop_evt = _stop_events.get(session_id)

    try:
        sniffer = AsyncSniffer(iface=child_session.iface, filter=child_session.bpf, store=True)
        _sniffer_handles[session_id] = sniffer
        sniffer.start()
        log.info("[%s] sniffer armed (iface=%s, output=%s)", session_id, child_session.iface, child_session.outfile)
        if armed_evt is not None:
            armed_evt.set()  # signal: sniffer armed

        # # Wait until duration elapses OR someone calls /done (stop_evt.set())
        # if stop_evt is not None:
        #     stop_evt.wait(timeout=duration)
        # else:
        #     time.sleep(duration)

        # Monitor + wait: stop event OR duration
        poll_log_interval = 30  # seconds
        last_size = -1
        start_time = time.time()

        while True:
            # check stop event
            if stop_evt is not None and stop_evt.is_set():
                log.info("[%s] stop_evt detected → stopping sniffer", session_id)
                break

            # check timeout
            elapsed = time.time() - start_time
            if elapsed >= duration:
                log.info("[%s] duration reached (elapsed=%.1fs / duration=%.1fs) → stopping sniffer",
                         session_id, elapsed, duration)
                break

            # file growth debug
            if os.path.exists(child_session.outfile):
                size = os.path.getsize(child_session.outfile)
                if size != last_size:
                    delta = (size - last_size) if last_size >= 0 else size
                    log.debug("[%s] pcap size: %d bytes (+%d)", session_id, size, delta)
                    last_size = size
                else:
                    log.debug("[%s] pcap steady at %d bytes", session_id, size)
            else:
                log.debug("[%s] pcap not created yet", session_id)

            time.sleep(poll_log_interval)

        packets = sniffer.stop()
        child_session.packets = len(packets) if packets is not None else 0
        if child_session.packets == 0:
            log.warning(f"[{session_id}] 0 packets captured")
        wrpcap(child_session.outfile, packets)
        log.info(f"[{session_id}] wrote {child_session.outfile}")

        if child_session.packets > 0:
            _split_streams_tshark(
                input_pcap=child_session.outfile,
                output_dir=child_session.child_dir,
                dir_code=child_session.code,
                timestamp=timestamp,
                min_packets=30,
                require_serverhello=True,
                require_appdata=False,
                force_tls_port="443",
            )
    except Exception as e:
        child_session.error = str(e)
        log.exception(f"[{session_id}] capture error: {e}")
    finally:
        child_session.done = True
        _sniffer_handles.pop(session_id, None)
        _stop_events.pop(session_id, None)


def _validate_targets(targets: list) -> None:
    """
    Validates that the targets list is not empty.
    """
    if not targets:
        raise HTTPException(status_code=400, detail="targets must be non-empty")


def _generate_session_code(target) -> str:
    """
    Generates a session code based on OS, browser, and algorithm.
    """
    return name_dir(target.os, target.browser, target.algo)


def _validate_interface(iface: str) -> None:
    """
    Validates if the specified interface exists.
    """
    if iface != "any":
        visible = set(get_if_list())
        if iface not in visible:
            raise HTTPException(status_code=400, detail=f"iface '{iface}' not found; available={sorted(visible)}")


def _create_output_directories(code: str, timestamp: str, ip: str) -> tuple[str, str]:
    """
    Creates output directories and returns the child directory and output file path.
    """
    if not os.path.exists(OUTPUT_ROOT):
        raise HTTPException(
            status_code=500,
            detail=f"Configuration Error: OUTPUT_ROOT '{OUTPUT_ROOT}' does not exist or is not mounted."
        )

    child_dir = os.path.join(OUTPUT_ROOT, code, f"session-{timestamp}")

    try:
        os.makedirs(child_dir, exist_ok=True)
    except OSError as e:
        log.error(f"Failed to create directory {child_dir}: {e}")
        raise HTTPException(status_code=500, detail=f"File system error: {e}")

    outfile = os.path.join(child_dir, f"raw.pcap")
    return child_dir, outfile


def _build_bpf_filter(target, ip: str) -> str:
    """
    Builds the BPF filter string based on the target's filter mode.
    """
    if target.filter_mode == "none":
        bpf = f"(host {ip}) and (ip or ip6)"
    elif target.filter_mode == "domain":
        if not target.domain:
            raise HTTPException(status_code=400, detail="domain required when filter_mode=domain")
        v4s, v6s = _resolve_domain_ips(target.domain)
        if not (v4s or v6s):
            raise HTTPException(status_code=424, detail=f"No A/AAAA records resolved for {target.domain}")
        bpf = _build_domain_bpf(ip, v4s, v6s)
    elif target.filter_mode == "custom":
        if not target.custom_bpf:
            raise HTTPException(status_code=400, detail="custom_bpf required when filter_mode=custom")
        bpf = f"(host {ip}) and ({target.custom_bpf})"
    else:
        raise HTTPException(status_code=400, detail="unknown filter_mode")
    return _and_ports(bpf, target.ports)


def _register_and_start_session(sid: str, cs: ChildSession, duration: int, timestamp: str) -> None:
    """
    Registers the child session, creates a stop event, and starts the capture job in a new thread.
    """
    with _lock:
        _sessions[sid] = cs
        _stop_events[sid] = Event()

    # Start thread and wait until "armed"
    armed = Event()
    threading.Thread(target=_capture_job, args=(sid, duration, timestamp, armed), daemon=True).start()
    if not armed.wait(timeout=2.0):
        log.warning("Sniffer %s did not arm within 2s (iface=%s, outfile=%s)", sid, cs.iface, cs.outfile)


def _start_single_target(target, timestamp: str, seen: set) -> dict | None:
    """
    Starts a single capture session for a given target.
    Helper for start_batch.
    """
    code = _generate_session_code(target)
    ip = str(target.container_ip)
    key = (ip, code)
    if key in seen:
        log.warning("Skipping duplicate target in batch: ip=%s code=%s", ip, code)
        return None
    seen.add(key)

    iface = str(target.iface) or "any"
    _validate_interface(iface)

    child_dir, outfile = _create_output_directories(code, timestamp, ip)
    bpf = _build_bpf_filter(target, ip)

    # Register session
    sid = uuid.uuid4().hex[:12]
    cs = ChildSession(
        session_id=sid,
        container_ip=ip,
        code=code,
        child_dir=child_dir,
        outfile=outfile,
        iface=iface,
        bpf=bpf,
        started_at=time.time(),
        duration_sec=target.duration_sec,
        session_count=getattr(target, "session_count", 1),
        qualified_target=int(getattr(target, "session_count", 1)),
    )

    _register_and_start_session(sid, cs, target.duration_sec, timestamp)

    return asdict(cs)


@app.post("/start", response_model=StartResponseMulti)
def start_batch(request: StartBatchRequest):
    """
    This function is responsible for starting a batch of sessions.
    It builds the BPF, arms the thread and creates the output directory.
    :param request: StartBatchRequest object
    :return: StartResponseMulti object
    """
    log.debug("/start (batch) called: %s", request.model_dump())
    _validate_targets(request.targets)

    # one UTC timestamp shared by this batch for easy grouping inside each code
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")

    children: list[dict] = []
    # de-dupe by (ip, code) to avoid double-sniffing the exact same thing in one call
    seen: set[tuple[str, str]] = set()

    for target in request.targets:
        child_data = _start_single_target(target, timestamp, seen)
        if child_data:
            children.append(child_data)

    return StartResponseMulti(started=True, children=children)


@app.get("/health")
def health():
    """
    Liveness/readiness probe endpoint.

    Returns:
        ``{"ok": True}`` when the service is up.
    """
    return "ok", 200


@app.get("/ifaces")
def list_ifaces() -> List[str]:
    """
    Return the list of interfaces visible inside the container.

    Returns:
        A list of interface names (e.g., ``["lo", "eth0"]``).
    """
    ifaces = get_if_list()
    log.debug(f"/ifaces -> {ifaces}")
    return ifaces


@app.get("/status", response_model=StatusAllResponse)
def status():
    with _lock:
        active = [sid for sid, cs in _sessions.items() if not cs.done]
        log.info("/status → %d sessions (active=%s)", len(_sessions), active)
        for sid, cs in _sessions.items():
            log.info("  [%s] done=%s packets=%d error=%s", sid, cs.done, cs.packets, cs.error)
        return StatusAllResponse(
            sessions=[asdict(cs) for cs in _sessions.values()])


@app.post("/done")
def done(req: DoneRequest = Body(...)):
    """
    Stop all active sessions that match the given container.
    Priority: container_ip (if provided) > resolve from url.
    Returns a list of session_ids that were signaled to stop.
    """
    try:
        if req.container_ip:
            target_ip = str(req.container_ip)
        elif req.url:
            target_ip = _resolve_ip_from_url(str(req.url))
        else:
            raise HTTPException(status_code=400, detail="container_ip or url required")

        to_stop: list[str] = []
        with _lock:
            for sid, cs in _sessions.items():
                if cs.container_ip == target_ip and not cs.done:
                    to_stop.append(sid)

        stopped: list[str] = []
        for sid in to_stop:
            evt = _stop_events.get(sid)
            if evt and not evt.is_set():
                evt.set()
                stopped.append(sid)

        return {
            "ok": True,
            "container_ip": target_ip,
            "stopped_session_ids": stopped,
            "active_count": len(stopped)
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("/done error: %s", e)
        raise HTTPException(status_code=500, detail="internal error")
