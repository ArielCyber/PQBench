# PQBench Sniffer Service

## Overview
The **Sender Service** is a Flask-based application responsible for generating synthetic network traffic by driving a real web browser (Selenium). It simulates user behavior (watching videos, playing games, browsing) to create traffic patterns that are then captured by the Sniffer service.

It supports Post-Quantum Cryptography (PQC) analysis by configuring browsers (Chrome/Firefox) to use specific Key Exchange algorithms (Kyber, ML-KEM) via internal flags.

## Project Structure

* **`entry.py`**: The Flask application entry point. Handles the `/execute` endpoint and health checks.
* **`sender.py`**: The abstract base class (`Sender`). Manages the lifecycle of a session (browser setup, config fetching, loop management) but delegates specific actions to components.
* **`sender_factory.py`**: Implements the Factory Pattern to instantiate the correct Sender subclass based on the requested "attribute" (e.g., Video, Map).
* **`page_interactor.py`**: A composite helper class that handles low-level Selenium interactions (Shadow DOM clicks, scrolling, iframe switching).
* **`browser_manager.py`**: Manages WebDriver instantiation and applies PQC algorithm strategies.
* **`algo_strategies.py`**: Defines the browser-specific flags for Non-PQC, Kyber, and ML-KEM modes.

---

## 1. Core Architecture

### The "Sender" Pattern
The service uses a mix of **Inheritance** (for traffic logic) and **Composition** (for capabilities).

1.  **Base Class (`Sender`)**:
    * Owns the `BrowserManager` (lifecycle), `ConfigService` (external API), and `PageInteractor` (actions).
    * Runs the main loop: `Setup -> Fetch Config -> Loop Sessions -> Teardown`.
    * **Abstract Method**: `create_traffic(interactor, button_data)` must be implemented by children.

2.  **Factory (`SenderFactory`)**:
    * Maps input strings to classes.
    * **Supported Attributes**:
        * `video` (VideoSender)
        * `game` (GameSender)
        * `map` (MapSender)
        * `audio` (AudioSender)
        * `browsing` (BrowserSender)
        * `download` (DownloadSender)
        * `cloud` (CloudSender)
        * `rtt` (RTTSender)

### Browser Configuration (Algo Strategies)
The service can launch browsers in three cryptographic modes, defined in `algo_strategies.py`:

* **Algo 0 (Non-PQC)**: Explicitly disables Kyber/ML-KEM.
* **Algo 1 (Kyber)**: Enables `enable-tls13-kyber` flags.
* **Algo 2 (ML-KEM)**: Enables `use-ml-kem` flags.

![img.png](images/sender_architecture.png)

---

## 2. Supported Traffic Attributes

The service handles 8 distinct traffic types. While they share the same browser core, their `create_traffic` logic differs:

### 1. Video (`VideoSender`)
* **Logic**: Clicks "Shadow" overlay buttons, finds the main "Play" button (searching iframes if necessary), and simulates a watch duration.
* **Fallback**: Uses JavaScript `element.play()` if standard clicks fail.

### 2. Game (`GameSender`)
* **Logic**: Searches for nickname fields (`input[name*='name']`), fills them, presses ENTER, clears overlays, and clicks "Play/Start".
* **Simulation**: Idles for `duration` seconds to simulate gameplay.

### 3. Map (`MapSender`)
* **Logic**: Uses `ActionChains` to click-and-drag (pan) the map canvas right and left.
* **Zoom**: Injects JavaScript `WheelEvent` to simulate zooming in and out.

### 4. Browsing (`BrowserSender`)
* **Logic**: Scrolls the page up/down and intelligently finds internal links (hrefs matching the current domain) to click, simulating a user navigating a site.

### 5. RTT (`RTTSender`)
* **Logic**: Focuses on continuous, rapid scrolling (up/down) to generate consistent Round Trip Time (RTT) measurements without heavy media loading.

*Note: Audio, Download, and Cloud senders follow similar patterns of interacting with specific page elements (audio players, download buttons, upload forms).*

---

## 3. API Reference

### `POST /execute`
Initiates a traffic generation session. This call blocks until the session finishes (or fails).

**Payload Schema:**
```json
{
  "browser": "chrome",        // "chrome" | "firefox"
  "algorithm": 2,             // 0=Non-PQC, 1=Kyber, 2=MLKEM
  "sessions": 1,              // Number of times to repeat the flow
  "domain": "[www.youtube.com](https://www.youtube.com)", // Target URL
  "attribute": "video"        // One of the 8 supported attributes
}
```

### `GET /health`
Returns `"ok", 200`.

---

## 4. Configuration & Environment

| Environment Variable | Description |
| :--- | :--- |
| `MODE` | Used by the root endpoint to serve static HTML (`KYBER` or `MLKEM`). |
| `CONFIG_SERVICE_URL` | URL of the `domain_maintainer` service (default: `http://domain_maintainer:5010`). |
| `CHROMEDRIVER_PATH` | Path to the local chromedriver binary. |
| `[ATTR]_WAIT_TIME` | Overrides wait time for specific attributes (e.g., `VIDEO_WAIT_TIME`). |

---

## 5. Page Interactor Capabilities
The `PageInteractor` class provides robust Selenium wrappers used by all Senders:

* **`click_shadow_button_advanced`**: Traverses the Shadow DOM to find and click deep elements.
* **`try_iframes`**: Recursively searches `<iframe>` tags if an element isn't found in the main DOM.
* **`force_play_media`**: Uses JavaScript execution to force `<video>` or `<audio>` tags to play, bypassing UI overlays.
* **`upload_file`**: Generates a dummy text file on the fly and pushes it to `input[type='file']`.
