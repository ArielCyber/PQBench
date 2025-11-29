# Switcher Service (Traffic Controller)

The Switcher is the core orchestration engine of the testing framework. It sits between the high-level **Agent** and the low-level infrastructure (Traffic Senders and Sniffers). Its primary job is to parse batch requests, manage concurrency, route commands to the correct Operating System containers, and synchronize the packet sniffer with the traffic generation.

# Overview

**Key Responsibilities:**
* **Routing:** Maps abstract requirements (e.g., "Linux + Kyber") to specific container URLs.
* **Concurrency Control:** Uses semaphores to ensure only one job runs per backend container at a time, while allowing parallel execution across *different* backends.
* **Sniffer Orchestration:** Automatically starts the sniffer before traffic begins and stops it when traffic ends.
* **Resolution:** DNS resolves container hostnames to IP addresses so the Sniffer knows which IP to filter.

# Configuration

The service is highly configurable via environment variables to adapt to different network topologies.

| Category | Variable | Default | Description |
| :--- | :--- | :--- | :--- |
| **Sniffer** | `SNIFFER_URL` | `http://172.18.0.1:8080` | URL of the Packet Sniffer API. |
| | `SNIFFER_POLL_INTERVAL_SEC` | `10` | How often to check if sniffing is done. |
| | `SWITCHER_STOP_ON_SENDER_DONE` | `true` | If `true`, stops sniffing immediately when the Sender finishes, ignoring the timeout. |
| **Backends** | `URL_LINUX_KYBER` | `http://linux-kyber:5000` | Address of the Linux Kyber container. |
| | `URL_WINDOWS_MLKEM` | `http://win-mlkem:5000` | Address of the Windows ML-KEM container. |
| | *(See `switcher.py` for full list)* | | |

# API Endpoints

### 1. Execute Batch (`POST /config`)
The main entry point used by the **Agent**.

* **Payload:** A JSON object containing a list of jobs.
* **Behavior:** Parallel execution (fan-out) limited by the `_EXECUTOR` thread pool (default 10 workers).
* **Response:** `207 Multi-Status`. A JSON body containing individual results for every job in the batch.

**Example Input:**
```json
{
  "jobs": [
    {
      "os": "windows",
      "browser": "chrome",
      "algorithm": "kyber",
      "sessions": 5
    }
  ]
}
```

### 2. Health Check (`GET /health`)
Returns `200 OK` if the Flask app is responsive.

# Orchestration Flow (Per Job)

1.  **Queue & Lock:** The job requests a specific backend (e.g., `windows_kyber`). It waits for the `Semaphore` lock for that specific container.
2.  **IP Resolution:** The Switcher resolves the target container's hostname to an internal Docker IP (e.g., `172.19.0.5`).
3.  **Sniffer Start:** Calls `POST /start` on the Sniffer service with the target IP and configuration.
4.  **Traffic Execution:** Calls `POST /execute` on the Traffic Sender container.
5.  **Monitoring:**
    * **Fast Path:** If the Sender reports "done", the Switcher immediately stops the Sniffer.
    * **Slow Path:** If the Sender times out or provides no status, the Switcher polls the Sniffer until all sessions are captured.
6.  **Cleanup:** Calls `POST /done` on the Sniffer to finalize the recording.
7.  **Unlock:** Releases the Semaphore, allowing the next job for this backend to proceed.
