import logging
import os
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Optional, List
import requests
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, IPvAnyAddress, constr
from scapy.all import AsyncSniffer, wrpcap, get_if_list  # uses libpcap under the hood

"""PQBench Sniffer: FastAPI microservice for capturing PCAPs inside a container.

Exposes /start, /status, /ifaces, and /health endpoints. Uses Scapy (libpcap)
to capture packets, builds BPF filters from several modes (none/domain/cidr/
ranges/custom), can intersect with TCP ports, and optionally splits TCP streams
with tshark into per-stream PCAPs.
"""

app = FastAPI(title="PQBench Sniffer", version="0.1")

# --------- Logging ----------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

log = logging.getLogger("pqbench.sniffer")

# ---------- Config ----------
OUTPUT_ROOT = os.environ.get("OUTPUT_ROOT", "/output")

# ---------- State ----------
_lock = threading.Lock()
_active = {"running": False, "started_at": None, "target_ip": None, "outfile": None}


# ---------- Models ----------
class StartRequest(BaseModel):
    """Request body for the ``POST /start`` endpoint.

    Attributes:
        os: Target OS label used in session naming. Accepts ``"linux"``,
            ``"windows"``, or ``"macos"``.
        browser: Browser label used in session naming. Accepts ``"chrome"``
            or ``"firefox"``.
        algo: Algorithm code used in session naming.
            ``0`` = Non-PQC, ``1`` = Kyber, ``2`` = MLKEM.
        container_ip: IP address of the target container whose traffic will
            be filtered (host <container_ip>).
        duration_sec: Capture duration in seconds (1–3600).
        iface: Network interface to capture on. Use ``"any"`` to sniff on all.
        split_streams: If ``True``, split TCP streams into individual PCAPs
            with tshark after capture (best effort).
        filter_mode: Filter construction strategy. One of:
            ``"none" | "domain" | "cidr" | "ranges" | "custom"``.
        domain: FQDN to resolve when ``filter_mode="domain"``.
        cidrs: Comma-separated IPv4/IPv6 CIDR list when
            ``filter_mode="cidr"`` (e.g., ``"31.13.64.0/18,2a03:2880::/32"``).
        ranges_v4_url: HTTP(S) URL that returns newline-separated IPv4 CIDRs
            when ``filter_mode="ranges"``.
        ranges_v6_url: HTTP(S) URL that returns newline-separated IPv6 CIDRs
            when ``filter_mode="ranges"``.
        ports: Optional comma-separated TCP ports to AND with the base BPF
            (e.g., ``"443"`` or ``"443,80"``).
        custom_bpf: Full BPF expression when ``filter_mode="custom"``.
    """
    os: constr(strip_whitespace=True) = Field(description="linux/windows/macos (for name_dir)")
    browser: constr(strip_whitespace=True) = Field(description="chrome/firefox (for name_dir)")
    algo: int = Field(ge=0, le=2, description="0=Non-PQC, 1=Kyber, 2=MLKEM")
    container_ip: IPvAnyAddress = Field(description="Target container IP to sniff")
    duration_sec: int = Field(60, ge=1, le=3600, description="How long to capture")
    iface: Optional[str] = Field(default="any", description="Interface to capture on (default: any)")
    split_streams: bool = Field(default=True, description="Whether to split TCP streams with tshark")
    filter_mode: constr(strip_whitespace=True) = Field(
        default="domain",
        description="one of: none | domain | cidr | ranges | custom"
    )
    domain: Optional[str] = Field(default="pq.cloudflareresearch.com",
                                  description="When filter_mode=domain, FQDN to resolve and filter on")
    cidrs: Optional[str] = Field(default=None,
                                 description="Comma-separated CIDRs for filter_mode=cidr,"
                                             " e.g. '31.13.64.0/18, 2a03:2880::/32'")
    ranges_v4_url: Optional[str] = Field(default=None, description="HTTP(s) URL returning newline-separated IPv4 CIDRs")
    ranges_v6_url: Optional[str] = Field(default=None, description="HTTP(s) URL returning newline-separated IPv6 CIDRs")
    ports: Optional[str] = Field(default=None, description="Comma-separated TCP ports to AND with the filter,"
                                                           "e.g. '443,80'")
    custom_bpf: Optional[str] = Field(default=None, description="When filter_mode=custom, full BPF filter")


class StartResponse(BaseModel):
    """Response body returned by ``POST /start``.

    Attributes:
        started: ``True`` if the capture task was scheduled.
        session_dir: Absolute path to the created session directory.
        outfile: Absolute path to the written raw PCAP file.
        iface: Interface used for capture (resolved from request).
        bpf: Final BPF string used by the sniffer (after port intersection).
    """
    started: bool
    session_dir: str
    outfile: str
    iface: str
    bpf: str


class StatusResponse(BaseModel):
    """Response body returned by ``GET /status``.

    Attributes:
        running: Whether a capture is currently in progress.
        started_at: Epoch seconds (UTC) when the capture began, if running.
        target_ip: The target container IP associated with the active/last run.
        outfile: The PCAP path for the active/last run, if available.
    """
    running: bool
    started_at: Optional[float]
    target_ip: Optional[str]
    outfile: Optional[str]


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
    """Build a bi-directional BPF limited to a container IP and a domain's IPs.

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


def _fetch_ranges(v4_url: Optional[str], v6_url: Optional[str]) -> tuple[List[str], List[str]]:
    """Fetch newline-separated IPv4/IPv6 CIDR lists from URLs.

    Args:
        v4_url: HTTP(S) URL for IPv4 CIDRs, or ``None``.
        v6_url: HTTP(S) URL for IPv6 CIDRs, or ``None``.

    Returns:
        A tuple ``(v4_cidrs, v6_cidrs)``; empty lists if URLs are ``None`` or on error.

    Notes:
        Network errors are logged and result in empty output lists.
    """
    v4: List[str] = []
    v6: List[str] = []
    try:
        if v4_url:
            v4 = [x.strip() for x in requests.get(v4_url, timeout=10).text.splitlines() if x.strip()]
        if v6_url:
            v6 = [x.strip() for x in requests.get(v6_url, timeout=10).text.splitlines() if x.strip()]
        log.info("Fetched ranges: ipv4=%d ipv6=%d", len(v4), len(v6))
        log.debug("Ranges samples v4=%s v6=%s", v4[:5], v6[:5])
    except Exception as e:
        log.exception("Failed to fetch ranges: %s", e)
    return v4, v6


def _build_cidr_bpf(container_ip: str, cidrs_v4: List[str], cidrs_v6: List[str]) -> str:
    """Build a bi-directional BPF limited to a container IP and CIDR ranges.

    Args:
        container_ip: Target container IP.
        cidrs_v4: IPv4 CIDR prefixes.
        cidrs_v6: IPv6 CIDR prefixes.

    Returns:
        A BPF string combining IPv4/IPv6 clauses. Falls back to ``ip or ip6`` if empty.
    """
    v4_parts = [f"(dst net {c} or src net {c})" for c in cidrs_v4]
    v6_parts = [f"(dst net {c} or src net {c})" for c in cidrs_v6]
    v4_clause = f"(ip and ({' or '.join(v4_parts)}))" if v4_parts else ""
    v6_clause = f"(ip6 and ({' or '.join(v6_parts)}))" if v6_parts else ""
    clause = " or ".join([c for c in [v4_clause, v6_clause] if c]) or "ip or ip6"
    return f"(host {container_ip}) and ({clause})"


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


def _capture_job(outfile: str, iface: str, bpf: str, duration: int, do_split: bool, session_dir: str):
    """Worker that performs the actual packet capture and optional stream splitting.

        Args:
            outfile: Destination PCAP path.
            iface: Interface passed to Scapy's ``AsyncSniffer`` (e.g., ``"any"`` or ``"eth0"``).
            bpf: Final BPF filter string.
            duration: Capture duration in seconds.
            do_split: If ``True``, attempt stream splitting with tshark after capture.
            session_dir: Session directory used for derived outputs (e.g., ``streams/``).

        Side Effects:
            Writes ``outfile`` (PCAP). Optionally writes ``streams/stream-*.pcap``.

        Notes:
            Any exception during capture is logged; service state is cleaned before exit.
        """
    log.info(f"Capture job starting: iface={iface} duration={duration}s outfile={outfile}")
    log.debug(f"Capture BPF: {bpf}")
    try:
        sniffer = AsyncSniffer(iface=iface, filter=bpf, store=True)
        sniffer.start()
        log.debug("AsyncSniffer started; sleeping for duration...")
        time.sleep(duration)
        packets = sniffer.stop()
        count = len(packets) if packets is not None else 0
        log.info(f"Capture stopped. Packets captured: {count}")
        if count == 0:
            log.warning("No packets captured. Check iface/BPF/visibility.")
        wrpcap(outfile, packets)
        log.info(f"Wrote pcap: {outfile} (exists={os.path.exists(outfile)})")
        if do_split and count > 0:
            _split_streams_tshark(outfile, os.path.join(session_dir, "streams"))
    except Exception as e:
        log.exception(f"Capture job error: {e}")
    finally:
        with _lock:
            _active.update({"running": False, "target_ip": None, "outfile": None, "last_bpf": None})
        log.debug("Capture job cleaned up state.")


@app.post("/start", response_model=StartResponse)
def start_capture(request: StartRequest, tasks: BackgroundTasks):
    """Start a capture session.

        Validates the request, constructs a BPF per ``filter_mode`` (optionally
        intersected with ``ports``), prepares a session directory named with the
        compact UTC timestamp and ``name_dir`` code, and schedules the background
        capture job.

        Args:
            request: ``StartRequest`` payload describing capture parameters.
            tasks: FastAPI background task manager.

        Returns:
            ``StartResponse`` containing session metadata and the final BPF.

        Raises:
            HTTPException:
                * ``400`` for invalid parameters (unknown filter_mode, missing
                  domain/cidrs/ranges/custom_bpf, or invalid iface).
                * ``409`` if a capture is already running.
                * ``424`` if domain resolution yields no A/AAAA records.
        """
    log.debug("/start called with: %s", request.dict())
    with _lock:
        if _active["running"]:
            raise HTTPException(status_code=409, detail="A capture is already running")

        folder_code = name_dir(request.os, request.browser, request.algo)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        session_dir = os.path.join(OUTPUT_ROOT, folder_code, f"session-{ts}")
        os.makedirs(session_dir, exist_ok=True)
        outfile = os.path.join(session_dir, "raw.pcap")
        log.debug("Session dir prepared: %s", session_dir)

        # Check that iface is correct
        visible = set(get_if_list())
        chosen = (request.iface or "any")
        if chosen != "any" and chosen not in visible:
            raise HTTPException(status_code=400, detail=f"iface '{chosen}' not found; available={sorted(visible)}")

        # Build filter
        if request.filter_mode == "none":
            bpf = f"(host {request.container_ip}) and (ip or ip6)"
        elif request.filter_mode == "domain":
            if not request.domain:
                raise HTTPException(status_code=400, detail="domain required when filter_mode=domain")
            v4s, v6s = _resolve_domain_ips(request.domain)
            if not (v4s or v6s):
                raise HTTPException(status_code=424, detail=f"No A/AAAA records resolved for {request.domain}")
            bpf = _build_domain_bpf(str(request.container_ip), v4s, v6s)
        elif request.filter_mode == "cidr":
            if not request.cidrs:
                raise HTTPException(status_code=400, detail="cidrs required when filter_mode=cidr")
            # split once, then classify into v4/v6 by presence of ':'
            raw = [c.strip() for c in request.cidrs.split(",") if c.strip()]
            v4 = [c for c in raw if ":" not in c]
            v6 = [c for c in raw if ":" in c]
            bpf = _build_cidr_bpf(str(request.container_ip), v4, v6)
        elif request.filter_mode == "ranges":
            # generic provider via URLs (works for Cloudflare, Facebook, Google, etc.)
            if not (request.ranges_v4_url or request.ranges_v6_url):
                raise HTTPException(status_code=400,
                                    detail="ranges_v4_url and/or ranges_v6_url required when filter_mode=ranges")
            v4, v6 = _fetch_ranges(request.ranges_v4_url, request.ranges_v6_url)
            bpf = _build_cidr_bpf(str(request.container_ip), v4, v6)
        elif request.filter_mode == "custom":
            if not request.custom_bpf:
                raise HTTPException(status_code=400, detail="custom_bpf required when filter_mode=custom")
            bpf = f"(host {request.container_ip}) and ({request.custom_bpf})"

        else:
            raise HTTPException(status_code=400, detail="unknown filter_mode")

        bpf = _and_ports(bpf, request.ports)
        # Mark active and launch background capture
        _active.update({
            "running": True,
            "started_at": time.time(),
            "target_ip": str(request.container_ip),
            "outfile": outfile
        })
        log.info("Scheduling capture: iface=%s target=%s duration=%ss split=%s",
                 request.iface or "any", request.container_ip, request.duration_sec, request.split_streams)

        tasks.add_task(_capture_job, outfile, request.iface or "any", bpf, request.duration_sec,
                       request.split_streams, session_dir)

        response = StartResponse(started=True, session_dir=session_dir, outfile=outfile,
                                 iface=request.iface or "any", bpf=bpf)
        log.debug("StartResponse: %s", response.dict())
        return response


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


@app.get("/status", response_model=StatusResponse)
def status():
    with _lock:
        log.debug(f"/status -> active={_active}")
        return StatusResponse(running=_active["running"],
                              started_at=_active["started_at"],
                              target_ip=_active["target_ip"],
                              outfile=_active["outfile"])
