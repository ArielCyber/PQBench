import logging
import os
import time
import json
import threading
import subprocess
from datetime import datetime
from typing import Optional, List
import socket
import requests
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, IPvAnyAddress, constr
from scapy.all import AsyncSniffer, wrpcap, get_if_list  # uses libpcap under the hood

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
CF_IPV4_URL = os.environ.get("CF_IPV4_URL", "https://www.cloudflare.com/ips-v4")
CF_IPV6_URL = os.environ.get("CF_IPV6_URL", "https://www.cloudflare.com/ips-v6")
FETCH_CF_ON_START = os.environ.get("CF_FETCH_ON_START", "true").lower() == "true"

log.debug(f"Config: OUTPUT_ROOT={OUTPUT_ROOT} CF_IPV4_URL={CF_IPV4_URL} "
          f"CF_IPV6_URL={CF_IPV6_URL} FETCH_CF_ON_START={FETCH_CF_ON_START} LOG_LEVEL={LOG_LEVEL}")

# ---------- State ----------
_lock = threading.Lock()
_active = {"running": False, "started_at": None, "target_ip": None, "outfile": None}

# ---------- Models ----------
"""
BaseModel comes from Pydantic, a library FastAPI uses to define data models.
A class that inherits from BaseModel is basically a schema:
    * It defines the expected fields (names, types, constraints).
    * It validates incoming data (e.g. ensures duration_sec is an int between 1 and 3600).
    * It auto-generates JSON serialization/deserialization.
    * FastAPI also uses it to auto-generate OpenAPI/Swagger docs for your API.
"""


class StartRequest(BaseModel):
    """
    This class defines the structure of the body of the /start POST request.
    """
    os: constr(strip_whitespace=True) = Field(description="linux/windows/macos (for name_dir)")
    browser: constr(strip_whitespace=True) = Field(description="chrome/firefox (for name_dir)")
    algo: int = Field(ge=0, le=2, description="0=Non-PQC, 1=Kyber, 2=MLKEM")
    container_ip: IPvAnyAddress = Field(description="Target container IP to sniff")
    duration_sec: int = Field(60, ge=1, le=3600, description="How long to capture")
    iface: Optional[str] = Field(default="any", description="Interface to capture on (default: any)")
    split_streams: bool = Field(default=True, description="Whether to split TCP streams with tshark")
    filter_mode: constr(strip_whitespace=True) = Field(default="cloudflare", description="cloudflare | custom")
    domain: Optional[str] = Field(default="pq.cloudflareresearch.com",
                                  description="When filter_mode=domain, FQDN to resolve and filter on")
    custom_bpf: Optional[str] = Field(default=None, description="When filter_mode=custom, full BPF filter")


class StartResponse(BaseModel):
    """
    This class defines the structure of the JSON response when /start is called.
    """
    started: bool
    session_dir: str
    outfile: str
    iface: str
    bpf: str


class StatusResponse(BaseModel):
    """
    This class defines what /status returns.
    """
    running: bool
    started_at: Optional[float]
    target_ip: Optional[str]
    outfile: Optional[str]


# ---------- Helpers ----------
def _resolve_domain_ips(hostname: str) -> tuple[list[str], list[str]]:
    """Return (v4_list, v6_list) unique IPs for the domain."""
    logging.debug("_resolve_domain_ips(): resolving %r", hostname)
    v4s: List[str] = []
    v6s: List[str] = []
    try:
        infos = socket.getaddrinfo(hostname, None)
        logging.debug("_resolve_domain_ips(): getaddrinfo returned %d records", len(infos))
        for family, _, _, _, sockaddr in infos:
            if family == socket.AF_INET:
                ip = sockaddr[0]
                if ip not in v4s:
                    v4s.append(ip)
            elif family == socket.AF_INET6:
                ip = sockaddr[0]
                if ip not in v6s:
                    v6s.append(ip)
        logging.debug("_resolve_domain_ips(): v4=%s | v6=%s", v4s, v6s)
    except Exception as e:
        logging.exception("_resolve_domain_ips(): failed to resolve %r: %s", hostname, e)
    return v4s, v6s


def _build_domain_bpf(container_ip: str, domain_v4: List[str], domain_v6: List[str]) -> str:
    """
    (host <container_ip>) and ( (ip and (src host IP or dst host IP ...)) or (ip6 ... ) )
    Include both directions so we catch requests and responses.
    """
    logging.debug("_build_domain_bpf(): container=%s v4=%s v6=%s", container_ip, domain_v4, domain_v6)
    v4_parts = [f"(dst host {ip} or src host {ip})" for ip in domain_v4]
    v6_parts = [f"(dst host {ip} or src host {ip})" for ip in domain_v6]

    v4_clause = f"(ip and ({' or '.join(v4_parts)}))" if v4_parts else ""
    v6_clause = f"(ip6 and ({' or '.join(v6_parts)}))" if v6_parts else ""
    clause = " or ".join([c for c in [v4_clause, v6_clause] if c])

    if not clause:
        logging.warning("_build_domain_bpf(): empty domain IP set; falling back to (ip or ip6)")
        clause = "ip or ip6"

    bpf = f"(host {container_ip}) and ({clause})"
    logging.debug("_build_domain_bpf(): BPF=%s", bpf)
    return bpf


def name_dir(os_name: str, browser: str, algo: int) -> str:
    """
    OS: Linux - 1, Windows - 2, MacOS - 3;
    Browser: Firefox - 1, chrome - 2;
    Algo: Non PQC - 0, Kyber - 1, MLKEM - 2
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


def _fetch_cloudflare_ranges() -> tuple[List[str], List[str]]:
    """
    Return (ipv4_ranges, ipv6_ranges) from Cloudflare official lists.
    """
    log.debug(f"Fetching Cloudflare ranges...")
    v4 = requests.get(CF_IPV4_URL, timeout=10).text.strip().splitlines()
    v6 = requests.get(CF_IPV6_URL, timeout=10).text.strip().splitlines()
    # Keep only non-empty lines
    v4 = [x.strip() for x in v4 if x.strip()]
    v6 = [x.strip() for x in v6 if x.strip()]
    log.info(f"Fetched Cloudflare ranges: ipv4={len(v4)} ipv6={len(v6)}")
    log.debug(f"Sample v4: {v4[:5]} | Sample v6: {v6[:5]}")
    return v4, v6


_CF_V4: List[str] = []
_CF_V6: List[str] = []


@app.get("/ifaces")
def list_ifaces() -> List[str]:
    """List interfaces visible inside this container."""
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


@app.get("/debug/cf")
def debug_cf():
    return {
        "v4_count": len(_CF_V4),
        "v6_count": len(_CF_V6),
        "v4_sample": _CF_V4[:5],
        "v6_sample": _CF_V6[:5],
        "urls": {"v4": CF_IPV4_URL, "v6": CF_IPV6_URL},
    }


def _build_cf_bpf(container_ip: str, cf_v4: List[str], cf_v6: List[str]) -> str:
    """
    Build a BPF that restricts traffic to the given container IP AND Cloudflare ranges.
    Includes both directions (src or dst CF).
    """
    # (host <container_ip>) AND ((ip and (src/dst net CFv4...)) OR (ip6 and (src/dst net CFv6...)))
    logging.debug("_build_cf_bpf(): container=%s cf_v4=%d cf_v6=%d", container_ip, len(cf_v4), len(cf_v6))
    v4_parts = [f"(dst net {cidr} or src net {cidr})" for cidr in cf_v4]
    v6_parts = [f"(dst net {cidr} or src net {cidr})" for cidr in cf_v6]

    v4_clause = f"(ip and ({' or '.join(v4_parts)}))" if v4_parts else ""
    v6_clause = f"(ip6 and ({' or '.join(v6_parts)}))" if v6_parts else ""
    cf_clause = " or ".join([c for c in [v4_clause, v6_clause] if c])

    if not cf_clause:
        logging.warning("_build_cf_bpf(): CF lists empty; falling back to (ip or ip6)")
        # Fallback: just the container host (shouldn't happen if CF fetch works)
        cf_clause = "ip or ip6"

    bpf = f"(host {container_ip}) and ({cf_clause})"
    log.debug(f"BPF built (len={len(bpf)}): {bpf}")
    return bpf


def _split_streams_tshark(input_pcap: str, output_dir: str):
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
    except subprocess.CalledProcessError as e:
        log.error(f"tshark failed: {e}")
    except Exception as e:
        log.exception(f"Unexpected error during stream split: {e}")


def _capture_job(outfile: str, iface: str, bpf: str, duration: int, do_split: bool, session_dir: str):
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
def start_capture(req: StartRequest, tasks: BackgroundTasks):
    logging.debug("/start called with: %s", req.dict())
    with _lock:
        if _active["running"]:
            raise HTTPException(status_code=409, detail="A capture is already running")

        code = name_dir(req.os, req.browser, req.algo)
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        session_dir = os.path.join(OUTPUT_ROOT, code, f"session-{ts}")
        os.makedirs(session_dir, exist_ok=True)
        outfile = os.path.join(session_dir, "raw.pcap")
        logging.debug("Session dir prepared: %s", session_dir)

        # Build filter
        if req.filter_mode == "custom":
            if not req.custom_bpf:
                raise HTTPException(status_code=400, detail="custom_bpf required when filter_mode=custom")
            bpf = f"(host {req.container_ip}) and ({req.custom_bpf})"
            logging.debug("Using custom BPF: %s", bpf)
        elif req.filter_mode == "domain":
            if not req.domain:
                raise HTTPException(status_code=400, detail="domain required when filter_mode=domain")
            v4s, v6s = _resolve_domain_ips(req.domain)
            bpf = _build_domain_bpf(str(req.container_ip), v4s, v6s)
        else:
            bpf = _build_cf_bpf(str(req.container_ip), _CF_V4, _CF_V6)

        # Mark active and launch background capture
        _active.update({
            "running": True,
            "started_at": time.time(),
            "target_ip": str(req.container_ip),
            "outfile": outfile
        })
        logging.info("Scheduling capture: iface=%s target=%s duration=%ss split=%s",
                    req.iface or "any", req.container_ip, req.duration_sec, req.split_streams)

        tasks.add_task(_capture_job, outfile, req.iface or "any", bpf, req.duration_sec,
                       req.split_streams, session_dir)

        resp = StartResponse(started=True, session_dir=session_dir, outfile=outfile,
                             iface=req.iface or "any", bpf=bpf)
        logging.debug("StartResponse: %s", resp.dict())
        return resp


# ---------- Lifespan: fetch Cloudflare ranges at startup ----------
@app.on_event("startup")
def _startup():
    global _CF_V4, _CF_V6
    log.info("Startup: initializing sniffer service...")
    try:
        ifaces = get_if_list()
        log.debug(f"Visible interfaces at startup: {ifaces}")
    except Exception as e:
        log.exception(f"Failed to list interfaces at startup: {e}")

    if FETCH_CF_ON_START:
        try:
            _CF_V4, _CF_V6 = _fetch_cloudflare_ranges()
        except Exception as e:
            log.exception(f"Failed to fetch Cloudflare ranges: {e}")
            _CF_V4, _CF_V6 = [], []
    else:
        log.info("Skipping Cloudflare ranges fetch on startup (CF_FETCH_ON_START=false)")
