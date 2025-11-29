# PQC Traffic Generation Framework

## Overview
This repository hosts a modular microservices framework designed to generate, capture, and analyze Post-Quantum Cryptography (PQC) encryption traffic. The system orchestrates multiple operating systems and browsers to create diverse cryptographic datasets for analysis.

## System Architecture

The system operates as a pipeline where a high-level request (e.g., "Run Kyber on all OSs") is broken down into specific jobs, routed to the correct infrastructure, and synchronized with network recording tools.

![System Diagram](images/active_recording_diagram.png)

### Workflow Description
1.  **Job Creation:** The **Agent** receives a request and expands it into a matrix of jobs (e.g., Linux/Windows x Chrome/Firefox).
2.  **Orchestration:** The **Switcher** queues these jobs, ensuring that only one test runs per OS container at a time to prevent port conflicts.
3.  **Preparation:** The **Switcher** instructs the **Sniffer** to start recording traffic for the target container's IP.
4.  **Execution:** The **Switcher** triggers the **Sender** (Linux/Windows/MacOS) to launch the browser and visit the target domain.
5.  **Data Lookup:** The **Sender** queries the **Domain Maintainer** to know how to interact with the specific website (e.g., which button to click).
6.  **Capture & Process:** Once the traffic finishes, the **Sniffer** stops recording and post-processes the PCAP file to extract valid TLS streams.

---

## Service Components

### 1. Agent (Orchestrator)
* **Role:** The entry point for the framework.
* **Function:** Accepts high-level experiment parameters (e.g., `{"algorithm": "kyber"}`). It calculates all missing permutations (Smart Matrix) to ensure comprehensive testing coverage and forwards precise job lists to the Switcher.

### 2. Switcher (Traffic Controller)
* **Role:** Concurrency manager and router.
* **Function:**
    * Maintains a queue for each backend container to prevent collisions.
    * Resolves container hostnames to internal Docker IPs.
    * Synchronizes the start/stop of the **Sniffer** with the **Sender** execution.

### 3. Sniffer (Network Recorder)
* **Role:** Packet capture and processing.
* **Function:**
    * Uses `Scapy` (libpcap) to record traffic on the bridge network.
    * Applies strict BPF filters to capture only relevant traffic (Container IP <-> Target Domain).
    * Uses `tshark` to split raw PCAP files into individual, clean TLS sessions.

### 4. Senders (Traffic Generators)
* **Variants:** `sender_linux`, `sender_windows`, `sender_macos`
* **Role:** The "workers" running the browsers.
* **Function:** These containers run QEMU/KVM (for Windows/Mac) or native browsers (Linux) to generate the actual encrypted web traffic using specific PQC algorithms (Kyber, ML-KEM).

### 5. Domain Maintainer (Data Provider)
* **Role:** Configuration database.
* **Function:** A FastAPI service backed by an Excel sheet (`domain_data.xlsx`). It provides the Senders with specific CSS selectors and DOM element IDs needed to interact with complex websites (e.g., clicking "Play" on a video platform).

### 6. Infrastructure
* **docker-compose:** Orchestrates the deployment of the entire stack, handling networking and shared volumes.
* **.env:** Centralized configuration for environment variables (ports, URLs, logging levels).
