from typing import Optional, List
from dataclasses import dataclass
from pydantic import BaseModel, Field, IPvAnyAddress, constr, AnyUrl

# --- types.py (or keep inside sniffer.py if you prefer one file) ---
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, IPvAnyAddress, constr
from dataclasses import dataclass

class TargetSpec(BaseModel):
    # recording identity (governs folder code)
    os: constr(strip_whitespace=True) = Field(description="linux/windows/macos")
    browser: constr(strip_whitespace=True) = Field(description="chrome/firefox")
    algo: int = Field(ge=0, le=2, description="0=Non-PQC, 1=Kyber, 2=MLKEM")
    session_count: int = Field(1, ge=1, le=1000, description="Number of independent recordings to make")

    # capture identity
    container_ip: IPvAnyAddress

    # capture options (per-target)
    duration_sec: int = Field(5, ge=1, le=3600)
    iface: Optional[str] = "any"

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
    session_count: int = 1
    done: bool = False
    packets: int = 0
    error: Optional[str] = None

class DoneRequest(BaseModel):
    container_ip: Optional[IPvAnyAddress] = None
    url: Optional[AnyUrl] = None
