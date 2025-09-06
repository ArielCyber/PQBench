## Sniffer API – `/start` Request

The `/start` endpoint launches a packet capture session inside the sniffer container.

### Definitions

* **BPF** – a network tap and packet filter which permits computer network packets to be captured and filtered at the operating system level.
* **CIDR** – a method for allocating and routing IP addresses.
* **iface** – stands for "network interface". It tells Scapy’s AsyncSniffer which interface to attach to when capturing packets. Examples: `eth0`, `lo`, `wlan0`, `docker0`, `any`.
* **BaseModel (Pydantic)** – A class that inherits from Pydantic’s BaseModel is basically a schema:

  * Defines expected fields (names, types, constraints).
  * Validates incoming data (e.g., ensures `duration_sec` is an int between 1 and 3600).
  * Auto-generates JSON serialization/deserialization.
  * FastAPI also uses it to auto-generate OpenAPI/Swagger docs for your API.
* **Naming scheme encoding** – encodes OS, browser, and algorithm into a 3‑digit string for session naming:

  * **OS**: Linux = 1, Windows = 2, MacOS = 3
  * **Browser**: Firefox = 1, Chrome = 2
  * **Algorithm**: Non‑PQC = 0, Kyber = 1, MLKEM = 2
  * **For example**: `121` means Linux (1), Chrome (2), Kyber (1).

---

### Request Schema

```jsonc
"targets": [
            {
                "os": os_name,              // linux | windows | macos
                "browser": browser,         // chrome | firefox
                "algo": algo,               // 0 = Non-PQC, 1 = Kyber, 2 = MLKEM
                "container_ip": my_ip,      // Target container IP to sniff
                "duration_sec": duration,   // Capture length in seconds (1–3600)
                "iface": iface,             // Network interface ("any", "pqbench0", "eth0", etc.)
                "filter_mode": "domain",    // one of: none | domain | custom
                "domain": domain,           // required if filter_mode=domain
                "ports": "443,80",          // optional: restrict capture to these TCP ports
                "custom_bpf": "tcp and port 443 and not host 10.0.0.1" // required if filter_mode=custom
            },
            {
                "os": "linux",                  
                "browser": "chrome",            
                "algo": 1,                      
                "container_ip": "172.28.0.23",  
                "duration_sec": 60,             
                "iface": "any",                 
                "filter_mode": "domain",     
                "domain": "pq.cloudflare.com"
            }
        ]
```

---

### Filter Modes

* **`none`**
  Capture all traffic to/from the container IP (optionally restricted by `ports`).

  ```json
  { "filter_mode": "none", "ports": "443" }
  ```

* **`domain`**
  Resolve a domain to IPv4/IPv6 and capture only that traffic.

  ```json
  { "filter_mode": "domain", "domain": "facebook.com", "ports": "443" }
  ```

* **`custom`**
  Supply a full BPF expression directly.

  ```json
  {
    "filter_mode": "custom",
    "custom_bpf": "tcp and port 443 and not host 10.0.0.1"
  }
  ```

---

### Response

```json
{
  "started": true,
  "children": [
    {
      "session_id": "a8f32c9d12ab",
      "container_ip": "172.18.0.10",
      "code": "122",
      "child_dir": "../output/122/session-20250905T145711Z",
      "outfile": "../output/122/session-20250905T145711Z/raw-172.18.0.10.pcap",
      "iface": "pqbench0",
      "bpf": "(host 172.18.0.10) and ((ip and ((dst host 104.18.30.220 or src host 104.18.30.220) or (dst host 104.18.31.220 or src host 104.18.31.220)))) and (tcp port 443)",
      "started_at": 1693923423.12345,
      "duration_sec": 60,
      "done": false,
      "packets": 0,
      "error": null
    },
    {
      "session_id": "d94b7f3810c3",
      "container_ip": "172.18.0.11",
      "code": "110",
      "child_dir": "../output/110/session-20250905T145711Z",
      "outfile": "../output/110/session-20250905T145711Z/raw-172.18.0.11.pcap",
      "iface": "pqbench0",
      "bpf": "(host 172.18.0.11) and ((ip and ((dst host 104.18.30.220 or src host 104.18.30.220) or (dst host 104.18.31.220 or src host 104.18.31.220)))) and (tcp port 443)",
      "started_at": 1693923423.45678,
      "duration_sec": 60,
      "done": false,
      "packets": 0,
      "error": null
    }
  ]
}

```