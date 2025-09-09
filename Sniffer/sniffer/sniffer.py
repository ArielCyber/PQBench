import logging
import os
import socket
import subprocess
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from scapy.all import AsyncSniffer, wrpcap, get_if_list  # uses libpcap under the hood
from sessions import *
from threading import Event

"""
PQBench Sniffer: FastAPI microservice for capturing PCAPs inside a container.

Exposes /start, /status, /ifaces, and /health endpoints. Uses Scapy (libpcap)
to capture packets, builds BPF filters from several modes (none/domain/cidr/
ranges/custom), can intersect with TCP ports, and optionally splits TCP streams
with tshark into per-stream PCAPs.
"""

app = FastAPI(title="PQBench Sniffer", version="0.1.1")

# --------- Logging ----------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

log = logging.getLogger("pqbench.sniffer")

# ---------- Config ----------
OUTPUT_ROOT = os.environ.get("OUTPUT_ROOT", "../output")

# ---------- State ----------
_lock = threading.Lock()
_active = {"running": False, "started_at": None, "target_ip": None, "outfile": None}
# All child sessions keyed by session_id
_sessions: dict[str, ChildSession] = {}

# remember the most recent parent run (for convenience in /status)
_last_parent = {"session_dir": None, "children": []}

# ---------- Helpers ----------
def _resolve_domain_ips(hostname: str) -> tuple[list[str], list[str]]:
    """Resolve a domain to unique IPv4/IPv6 addresses.

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
    """Build a bidirectional BPF limited to a container IP and a domain's IPs.

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
    """Encode OS, browser, and algorithm into a 3-digit session code.

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
        log.error(f"name_dir invalid input: {e}")
        raise ValueError(f"Invalid input: {e.args[0]}")

    code = f"{os_num}{browser_num}{algo}"
    log.debug(f"name_dir -> os={os_name} browser={browser} algo={algo} => {code}")
    return code


def _and_ports(bpf: str, ports_csv: Optional[str]) -> str:
    """AND a TCP port clause with an existing BPF, if ports were supplied.

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


def _split_streams_tshark(input_pcap: str, output_dir: str):
    """Split TCP streams from a PCAP into per-stream PCAP files using tshark.

        Extracts unique ``tcp.stream`` IDs, then writes each stream to
        ``<output_dir>/stream-<id>.pcap``.

        Args:
            input_pcap: Path to the input PCAP file.
            output_dir: Directory to write per-stream files into (created if missing).

        Side Effects:
            Writes ``stream-*.pcap`` files to ``output_dir``.

        Notes:
            If tshark is not installed, a warning is logged and splitting is skipped.
        """
    try:
        os.makedirs(output_dir, exist_ok=True)
        cmd_list_ids = ["tshark", "-r", input_pcap, "-T", "fields", "-e", "tcp.stream", "-Y", "tcp"]
        log.debug(f"Splitting streams: listing IDs with: {' '.join(cmd_list_ids)}")
        out = subprocess.check_output(cmd_list_ids, text=True)
        stream_ids = sorted(set([s for s in out.splitlines() if s.strip() != ""]))
        log.info(f"Streams found: {len(stream_ids)}")
        for sid in stream_ids:
            stream_out = os.path.join(output_dir, f"stream-{sid}.pcap")
            cmd_extract = ["tshark", "-r", input_pcap, "-w", stream_out, "-Y", f"tcp.stream=={sid}"]
            log.debug(f"Extracting stream {sid} -> {stream_out} | cmd={' '.join(cmd_extract)}")
            subprocess.run(cmd_extract, check=False)
    except FileNotFoundError:
        log.warning("tshark not found; skipping stream split")
    except subprocess.CalledProcessError as e:
        log.error(f"tshark failed: {e}")
    except Exception as e:
        log.exception(f"Unexpected error during stream split: {e}")


def _capture_job(session_id: str, duration: int, armed_evt: Event | None = None):
    cs = _sessions.get(session_id)
    if not cs:
        return
    log.info(f"[{session_id}] Capture start: ip={cs.container_ip} iface={cs.iface} outfile={cs.outfile}")
    log.debug(f"[{session_id}] BPF: {cs.bpf}")
    try:
        sniffer = AsyncSniffer(iface=cs.iface, filter=cs.bpf, store=True)
        sniffer.start()
        if armed_evt is not None:
            armed_evt.set()  # signal: sniffer armed
        time.sleep(duration)
        packets = sniffer.stop()
        cs.packets = len(packets) if packets is not None else 0
        if cs.packets == 0:
            log.warning(f"[{session_id}] 0 packets captured")
        wrpcap(cs.outfile, packets)
        log.info(f"[{session_id}] wrote {cs.outfile}")
        if cs.packets > 0:
            _split_streams_tshark(cs.outfile, os.path.join(cs.child_dir, "streams"))
    except Exception as e:
        cs.error = str(e)
        log.exception(f"[{session_id}] capture error: {e}")
    finally:
        cs.done = True


@app.post("/start", response_model=StartResponseMulti)
def start_batch(request: StartBatchRequest):
    log.debug("/start (batch) called: %s", request.model_dump())

    if not request.targets:
        raise HTTPException(status_code=400, detail="targets must be non-empty")

    # one UTC timestamp shared by this batch for easy grouping inside each code
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    children: list[dict] = []
    # de-dupe by (ip, code) to avoid double-sniffing the exact same thing in one call
    seen: set[tuple[str,str]] = set()

    for t in request.targets:
        code = name_dir(t.os, t.browser, t.algo)  # e.g., "122"
        ip = str(t.container_ip)
        key = (ip, code)
        if key in seen:
            log.warning("Skipping duplicate target in batch: ip=%s code=%s", ip, code)
            continue
        seen.add(key)

        # Validate interface *per target*
        iface = t.iface or "any"
        if iface != "any":
            visible = set(get_if_list())
            if iface not in visible:
                raise HTTPException(status_code=400, detail=f"iface '{iface}' not found; available={sorted(visible)}")

        # Per-target directory inside its code folder
        child_dir = os.path.join(OUTPUT_ROOT, code, f"session-{ts}")
        os.makedirs(child_dir, exist_ok=True)
        safe_ip = ip.replace(":", "_")
        outfile = os.path.join(child_dir, f"raw-{safe_ip}.pcap")

        # Per-target filter
        if t.filter_mode == "none":
            bpf = f"(host {ip}) and (ip or ip6)"
        elif t.filter_mode == "domain":
            if not t.domain:
                raise HTTPException(status_code=400, detail="domain required when filter_mode=domain")
            v4s, v6s = _resolve_domain_ips(t.domain)
            if not (v4s or v6s):
                raise HTTPException(status_code=424, detail=f"No A/AAAA records resolved for {t.domain}")
            bpf = _build_domain_bpf(ip, v4s, v6s)
        elif t.filter_mode == "custom":
            if not t.custom_bpf:
                raise HTTPException(status_code=400, detail="custom_bpf required when filter_mode=custom")
            bpf = f"(host {ip}) and ({t.custom_bpf})"
        else:
            raise HTTPException(status_code=400, detail="unknown filter_mode")
        bpf = _and_ports(bpf, t.ports)

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
            duration_sec=t.duration_sec,
        )
        with _lock:
            _sessions[sid] = cs

        # Start thread and wait until "armed"
        armed = Event()
        threading.Thread(target=_capture_job, args=(sid, t.duration_sec, armed), daemon=True).start()
        if not armed.wait(timeout=2.0):
            log.warning("Sniffer %s did not arm within 2s (iface=%s, outfile=%s)", sid, iface, outfile)

        children.append(asdict(cs))

    return StartResponseMulti(started=True, children=children)


# ---------- Lifespan: logs interfaces at startup ----------
@app.on_event("startup")
def _startup():
    """FastAPI startup hook: logs visible interfaces for diagnostics."""
    log.info("Startup: initializing sniffer service...")
    try:
        ifaces = get_if_list()
        log.debug(f"Visible interfaces at startup: {ifaces}")
    except Exception as e:
        log.exception(f"Failed to list interfaces at startup: %s", e)


@app.get("/health")
def health():
    """Liveness/readiness probe endpoint.

        Returns:
            ``{"ok": True}`` when the service is up.
    """
    return {"ok": True}


@app.get("/ifaces")
def list_ifaces() -> List[str]:
    """Return the list of interfaces visible inside the container.

    Returns:
        A list of interface names (e.g., ``["lo", "eth0"]``).
    """
    ifaces = get_if_list()
    log.debug(f"/ifaces -> {ifaces}")
    return ifaces


@app.get("/status", response_model=StatusAllResponse)
def status():
    with _lock:
        return StatusAllResponse(
            sessions=[asdict(cs) for cs in _sessions.values()]
        )
