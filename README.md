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
{
  "os": "linux",                  // linux | windows | macos
  "browser": "chrome",            // chrome | firefox
  "algo": 1,                      // 0 = Non-PQC, 1 = Kyber, 2 = MLKEM
  "container_ip": "172.28.0.23",  // Target container IP to sniff
  "duration_sec": 60,             // Capture length in seconds (1–3600)
  "iface": "any",                 // Network interface ("any", "eth0", etc.)
  "split_streams": true,          // Split TCP streams into individual pcaps
  "filter_mode": "domain",        // one of: none | domain | cidr | ranges | custom
  "domain": "facebook.com",       // required if filter_mode=domain
  "cidrs": "31.13.64.0/18,2a03:2880::/32", // required if filter_mode=cidr
  "ranges_v4_url": "https://example.com/ips-v4.txt", // required if filter_mode=ranges
  "ranges_v6_url": "https://example.com/ips-v6.txt",
  "ports": "443,80",              // optional: restrict capture to these TCP ports
  "custom_bpf": "tcp and port 443 and not host 10.0.0.1" // required if filter_mode=custom
}
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

* **`cidr`**
  Capture traffic limited to explicit CIDR blocks.

  ```json
  { "filter_mode": "cidr", "cidrs": "31.13.64.0/18,2a03:2880::/32" }
  ```

* **`ranges`**
  Fetch IPv4/IPv6 ranges from remote URLs (any provider).

  ```json
  {
    "filter_mode": "ranges",
    "ranges_v4_url": "https://example.com/ips-v4.txt",
    "ranges_v6_url": "https://example.com/ips-v6.txt",
    "ports": "443"
  }
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
  "session_dir": "/output/121/session-20250901T083000Z",
  "outfile": "/output/121/session-20250901T083000Z/raw.pcap",
  "iface": "any",
  "bpf": "(host 172.28.0.23) and (tcp port 443)"
}
```
