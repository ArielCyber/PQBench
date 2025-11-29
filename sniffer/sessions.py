from typing import Optional, List
from dataclasses import dataclass
from pydantic import BaseModel, Field, IPvAnyAddress, constr, AnyUrl

# --- types.py (or keep inside sniffer.py if you prefer one file) ---
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, IPvAnyAddress, constr
from dataclasses import dataclass

class TargetSpec(BaseModel):
    # recording identity (governs folder code)
    os: Literal["linux", "windows", "macos"]
    browser: Literal["chrome", "firefox"]
    algorithm: Literal["non-pqc", "kyber", "mlkem"]
    session: int = Field(1, ge=1, le=1000, description="Number of independent recordings to make")

    # capture identity
    container_ip: IPvAnyAddress

    # capture options (per-target)
    duration_sec: int = Field(5, ge=1, le=10800) # limited to 3 hours of sniffing
    iface: Optional[str] = "pqbench0"
    # filter options (per-target)
    filter_mode: Literal["none","domain","custom"] = "domain"
    domain: Optional[str] = "pq.cloudflareresearch.com"
    ports: Optional[str] = None
    custom_bpf: Optional[str] = None

class StartBatchRequest(BaseModel):
    targets: List[TargetSpec]

class StartResponseMulti(BaseModel):
    started: bool
    children: List[dict]  # ChildSession as dicts

class StatusAllResponse(BaseModel):
    sessions: List[dict]  # ChildSession as dicts

@dataclass
class ChildSession:
    session_id: str
    container_ip: str
    code: str                # 3-digit folder code (e.g., 122)
    child_dir: str           # output/<code>/session-<ts>
    outfile: str             # raw pcap path
    iface: str
    bpf: str
    started_at: float
    duration_sec: int
    session: int = 1         # Renamed from session_count to match input
    done: bool = False
    packets: int = 0
    error: Optional[str] = None

    qualified_streams: int = 0  # how many streams meet CH+SH+min_packets(+appdata)
    qualified_target: int = 0  # copy of session_count so we can expose it
    qualified_reached: bool = False  # set True once we hit/stabilize target
    last_progress_ts: Optional[float] = None

class DoneRequest(BaseModel):
    container_ip: Optional[IPvAnyAddress] = None
    url: Optional[AnyUrl] = None