# PQBench Sniffer Service

## Overview
The **PQBench Sniffer** is a FastAPI-based microservice designed to capture, filter, and post-process network traffic within containerized environments. It utilizes `scapy` for packet capture and `tshark` for post-processing stream separation.

The service is designed to handle multiple concurrent capture sessions, each targeting specific container IPs, employing custom BPF filters, and automatically organizing output based on OS, Browser, and Cryptographic Algorithm identifiers.

## Project Structure

* **`sniffer.py`**: The core application entry point. Contains the FastAPI app, threading logic, Scapy integration, and Tshark stream splitting logic.
* **`sessions.py`**: Contains Pydantic models (`TargetSpec`, `StartBatchRequest`) and Data Classes (`ChildSession`) used for type validation and state management.
* **`unit_test.py`**: `unittest` suite covering internal logic (BPF generation, directory naming) and mocked capture flows.
* **`api_test.py`**: `pytest` suite using `TestClient` to validate API endpoints and integration flows.

---

## 1. Core Architecture

### Capture Lifecycle
The system follows a specific flow for every batch request:

1.  **Request**: Client sends a batch of targets to `/start`.
2.  **Validation**: Inputs are validated via Pydantic models in `sessions.py`.
3.  **Session Creation**:
    * A unique Session Code is generated (e.g., `121` for Linux/Chrome/Kyber).
    * Output directories are created under `OUTPUT_ROOT//session-`.
    * A BPF filter is constructed based on the selected mode.
4.  **Threading**: A background thread is spawned for each target using `_capture_job`.
5.  **Capture**: `scapy.AsyncSniffer` records traffic to a raw `.pcap` file.
6.  **Termination**: Capture stops via timeout (`duration_sec`) or manual signal (`/done`).
7.  **Post-Processing**: The raw PCAP is passed to `_split_streams_tshark` to extract specific TCP streams.

### Directory Hierarchy & Naming Scheme
Outputs are organized using a 3-digit code derived from the target metadata.

* **Digit 1 (OS)**: 1=Linux, 2=Windows, 3=MacOS.
* **Digit 2 (Browser)**: 1=Firefox, 2=Chrome.
* **Digit 3 (Algo)**: 0=Non-PQC, 1=Kyber, 2=MLKEM.

**Example Path:**
`/output/121/session-2023-10-27_10-00-00/raw-172_18_0_5.pcap`.

---

## 2. API Reference

### `POST /start`
Initiates a batch of capture sessions.

**Payload Schema (`StartBatchRequest`):**
```jsonc
{
  "targets": [
    {
      "os": "linux",                    // linux | windows | macos
      "browser": "chrome",              // chrome | firefox
      "algo": 1,                        // 0=Non-PQC, 1=Kyber, 2=MLKEM
      "session_count": 1,               // Number of independent recordings (1-1000)
      "container_ip": "172.18.0.5",     // Target container IP
      "duration_sec": 60,               // Capture length (1–10800 seconds)
      "iface": "pqbench0",              // Interface (default "pqbench0")
      "filter_mode": "domain",          // none | domain | custom
      "domain": "pq.cloudflareresearch.com", // Required if filter_mode=domain
      "ports": "443"                    // Optional comma-separated ports
    }
  ]
}
```

### `POST /done`
Signals a running session to stop immediately before the duration expires.

**Payload (`DoneRequest`):**
* Provide either `container_ip` OR `url`.
* If `url` is provided, DNS resolution is attempted to find the target IP.

### `GET /status`
Returns the state of all active and completed sessions in memory, including packet counts and errors.

### `GET /ifaces`
Lists network interfaces visible to the container (useful for debugging network isolation).

### `GET /health`
Returns `"ok", 200` to indicate the service is running.

---

## 3. Key Logic & Internals

### BPF Filter Generation
The service supports three `filter_mode` strategies in `_build_bpf_filter`:

1.  **`none`**: Captures all traffic to/from the target container IP.
    * *Formula:* `(host ) and (ip or ip6)`
2.  **`custom`**: Appends a raw BPF string provided by the user.
    * *Formula:* `(host ) and ()`
3.  **`domain`**: Resolves a specific domain to *all* its IPv4/IPv6 addresses and captures traffic only between the container and those IPs.
    * *Formula:* `(host ) and (ip and (dst host ...))`

**Port Filtering:**
The helper `_and_ports` injects TCP port constraints (e.g., `tcp port 443`) into the final BPF string if specified.

### Stream Splitting (`_split_streams_tshark`)
After the raw capture finishes, `tshark` is invoked to split the raw PCAP into individual PCAP files per TCP stream.

**Selection Criteria:**
A stream is kept only if it meets **all** the following conditions:
1.  **ClientHello**: Must contain a TLS Handshake Type 1.
2.  **ServerHello**: Must contain a TLS Handshake Type 2 (enabled by `require_serverhello=True`).
3.  **Packet Count**: Must have at least `min_packets` (default 30) TCP frames.
4.  **App Data**: Must contain TLS Application Data (Content Type 23) (enabled by `require_appdata=True` in code, though currently set to `False` in the call).

**Output:**
* `.../streams/session---.pcap`: Individual stream files.
* `.../streams/_streams_debug.json`: Log of kept vs. dropped streams with reasons.

---

## 4. Configuration & Environment

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `OUTPUT_ROOT` | `/output` | Base directory for saving PCAP files. |
| `LOG_LEVEL` | `DEBUG` | Python logging level. |

---

## 5. Testing

The project uses a mix of `unittest` for unit testing and `pytest` for API integration testing.

### Running Unit Tests
Tests `sessions.py` and internal `sniffer.py` logic (mocking Scapy/Tshark).
```bash
python -m unittest unit_test.py
```

### Running API Tests
Tests the FastAPI endpoints using `TestClient`.
```bash
pytest api_test.py
```
