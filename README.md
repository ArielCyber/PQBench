# PQC macOS Container

This project allows running a macOS Big Sur container inside Docker to perform Post-Quantum Cryptography (PQC) tests with different browsers (Chrome/Firefox) and traffic capture tools.

---

## Installation and Usage Steps

### 1. Install macOS Big Sur in Docker
Run the following command once to pull and start macOS Big Sur in a new container:

```bash
docker run -it \
    --device /dev/kvm \
    -p 50922:10022 \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -e "DISPLAY=${DISPLAY:-:0.0}" \
    -e SHORTNAME=big-sur \
    sickcodes/docker-osx:latest
```

Afterwards, you can reuse the container with:

```bash
docker start -ai mymac
```

---

### 2. Project Directory
Inside the macOS container, go to the project directory (e.g., `~/pqcMac`).  
It should contain the following files:

- `setup.sh` – one-time installation script  
- `run.sh` – script to start the server  
- `processor.py` – main Python script  
- `requirements.txt` – Python dependencies  
- `venv/` – Python virtual environment  
- `images/`, `static/` – project resources  
- `kyber.pcap`, `mlkem.pcap`, `nonpqc.pcap` – traffic captures (optional)

---

### 3. One-Time Setup
Run the setup script to prepare the environment:

```bash
chmod +x setup.sh run.sh
./setup.sh
```

This will install the Python environment, dependencies, ChromeDriver, and Geckodriver.

---

### 4. Running the Project
Once setup is complete, start the server using:

```bash
./run.sh
```

The Flask server will be available at:
```
http://localhost:5000
```

Through the web UI you can choose:
- Operating System (MacOS / Linux / Windows)
- Browser (Chrome / Firefox)
- PQC Encryption (Non-PQC / Kyber / MLKEM)
- Session Count

---

### 5. Traffic Capture (Optional)
To capture PCAP files for analysis with Wireshark, use tcpdump:

```bash
sudo tcpdump -i en0 -w nonpqc.pcap
sudo tcpdump -i en0 -w kyber.pcap
sudo tcpdump -i en0 -w mlkem.pcap
```

The files will be saved in the project directory inside the container.

---

## Summary
- Run `setup.sh` once to install everything.  
- Run `run.sh` each time you want to start the project.  
- Use tcpdump if you want to capture and analyze traffic.  
