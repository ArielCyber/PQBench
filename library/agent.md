# Agent Service

The Agent acts as the orchestration entry point for traffic generation experiments. It receives high-level job requests, generates the necessary job matrices (permutations of OS, Browser, and Algorithms), and forwards the specific configurations to the **Switcher** service for execution.

# Overview

The Agent simplifies experiment management by offering two modes:
1.  **Manual Mode:** Pass a specific list of fully defined jobs.
2.  **Smart Matrix Mode:** Pass a partial configuration, and the Agent automatically generates all combinations of missing parameters (e.g., run on *all* OSs and *all* browsers).

# Configuration

The service is configured via environment variables.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ENTRY_CONTROLLER_URL` | `http://switcher:5000/config` | The URL of the Switcher service where processed job batches are sent. |
| `LOG_LEVEL` | `DEBUG` | Logging verbosity. |

# Usage

## API Endpoints

### 1. Run Specific Experiments (Manual)
Executes a precise list of job objects provided by the user.

* **Endpoint:** `POST /run_experiment`
* **Content-Type:** `application/json`

**Payload Example:**
```json
[
  {
    "os": "windows",
    "browser": "chrome",
    "algorithm": "kyber",
    "sessions": 10,
    "domain": "example.com"
  },
  {
    "os": "linux",
    "browser": "firefox",
    "algorithm": "non-pqc",
    "sessions": 5,
    "domain": "example.com"
  }
]
```

### 2. Run Smart Matrix (Auto-Generate)
Takes a base configuration and expands it into a full matrix for any missing fields. This is useful for "Run Everything" scenarios.

* **Endpoint:** `POST /all`
* **Content-Type:** `application/json`

**Matrix Logic:**
If a field is missing from the request, the Agent defaults to testing **all** supported options for that field:
* **OS:** `['linux', 'windows', 'macos']`
* **Browser:** `['chrome', 'firefox']`
* **Algorithm:** `['kyber', 'mlkem', 'non-pqc']`
* **Sessions:** Defaults to `5` if not specified.

**Payload Example (Run Kyber on ALL OSs and ALL Browsers):**
```json
{
  "algorithm": "kyber",
  "domain": "example.com",
  "sessions": 20
}
```
*Result: This generates 6 jobs (3 OSs × 2 Browsers) all running Kyber.*

### 3. Health Check
* **Endpoint:** `GET /health`
* **Response:** `"ok"`

# Flow

1.  **Request:** User sends a request to `/run_experiment` or `/all`.
2.  **Processing:**
    * If `/all`, the Agent calculates the cross-product of missing parameters.
    * If `/run_experiment`, it validates the list.
3.  **Logging:** The final JSON payload is saved locally to `last_sent_config.json` for debugging purposes.
4.  **Forwarding:** The payload is wrapped in `{"jobs": [...]}` and POSTed to the **Switcher** defined in `ENTRY_CONTROLLER_URL`.
5.  **Response:** The Agent returns the Switcher's response code and body to the user.
