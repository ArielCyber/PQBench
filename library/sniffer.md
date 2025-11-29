# Sniffer Service

The Sniffer is a specialized microservice responsible for capturing, filtering, and post-processing network traffic. It is designed to run in a privileged container with access to the host network or a shared bridge, allowing it to record traffic from other containers.

# Overview

The service performs two main functions:
1.  **Packet Capture (Live):** Uses `Scapy` (libpcap) to record traffic matching specific BPF filters (e.g., `host 172.18.0.5 and port 443`) into a raw PCAP file.
2.  **Stream Splitting (Post-Process):** Uses `tshark` (Wireshark CLI) to analyze the raw PCAP and extract individual valid TLS sessions into separate files.

# Requirements

* **System Tools:** `tshark` (must be installed in the container environment).
* **Python Libs:** `fastapi`, `scapy`, `pydantic`.
* **Privileges:** Must run with `NET_ADMIN` or similar capabilities to capture packets on the network interface.

# Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `OUTPUT_ROOT` | `/output` | Directory where captured PCAPs are saved. |
| `LOG_LEVEL` | `DEBUG` | Logging verbosity. |

# Usage

## API Endpoints

### 1. Start Capture (`POST /start`)
Initiates the recording process for one or more targets.

* **Body:** `StartBatchRequest`
    * `targets`: List of capture configurations.
* **TargetSpec:**
    * `os`, `browser`, `algorithm`: Metadata for naming the output folder.
    * `container_ip`: The specific IP to sniff.
    * `domain`: The target domain (e.g., `pq.cloudflareresearch.com`). The sniffer resolves this to IPs to build a precise BPF filter.
    * `duration_sec`: Max recording time (failsafe).

**Example Payload:**
```json
{
  "targets": [
    {
      "os": "linux",
      "browser": "chrome",
      "algorithm": "kyber",
      "container_ip": "172.19.0.5",
      "domain": "google.com",
      "duration_sec": 60
    }
  ]
}
```

### 2. Stop Capture (`POST /done`)
Signals the sniffer that the traffic generation is complete for a specific container. This triggers the stop of the recording and the start of post-processing.

**Example Payload:**
```json
{
  "container_ip": "172.19.0.5"
}
```

### 3. Check Status (`GET /status`)
Returns a list of all active and recently finished sessions, including packet counts and errors.

# Logic Flow

## 1. BPF Construction
To avoid capturing noise, the Sniffer builds a Berkeley Packet Filter (BPF) dynamically:
1.  Resolves `domain` to all its IPv4/IPv6 addresses.
2.  Constructs filter: `(host <CONTAINER_IP>) and (host <DOMAIN_IP_1> or host <DOMAIN_IP_2> ...)`.
3.  Appends port filters if specified.

## 2. Capture Loop
* A `Scapy` AsyncSniffer is launched in a background thread.
* It records until `duration_sec` expires OR a `/done` signal is received.
* Packets are written to `<OUTPUT_ROOT>/<os_browser_algo>/session-<timestamp>/raw.pcap`.

## 3. Post-Processing (TShark)
Once capture stops, `_split_streams_tshark` is called to clean the data:
1.  **Identify Streams:** Scans for TCP streams containing a **ClientHello** (TLS Handshake Type 1).
2.  **Validate:** Checks each stream for:
    * **ServerHello** (Handshake Type 2) - ensures the server accepted the connection.
    * **Minimum Packet Count** (default 30) - filters out dropped/incomplete connections.
    * **Application Data** - ensures actual data was exchanged.
3.  **Extract:** Saves valid streams as individual files: `session-<...>-01.pcap`, `session-<...>-02.pcap`, etc.
