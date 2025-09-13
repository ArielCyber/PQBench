# PQC macOS Container

This project allows running a macOS Big Sur container inside Docker to perform Post-Quantum Cryptography (PQC) tests with different browsers (Chrome/Firefox) and traffic capture tools.

---

## Installation and Usage Steps

### 1. Install macOS Big Sur in Docker
Run the following command once to pull and start macOS Big Sur in a new Docker container(*Using Docker-OSX):

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
Inside the macOS container, clone the correct branch from the repository:

```bash
git clone -b MacOS-Container https://github.com/ArielCyber/PQBench.git
cd PQBench
```

The project directory should contain the following files:

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

## Notes to the future

- **This is a full macOS VM, not a normal Docker image.**  
  We use `sickcodes/docker-osx` to boot a macOS Big Sur 11.7.10 guest. You must complete the macOS first-boot setup once (step 1). Without finishing the OS setup, you won’t be able to reuse the container.

- **Browser versions and OS support.**  
  Google Chrome no longer supports Big Sur. We pin **Chrome 138.0.7204.184** and install a matching **ChromeDriver 138**. **Firefox 142.0.1** is used on macOS Big Sur.

- **Architecture matters (Intel vs Apple Silicon).**  
  Inside `docker-osx` the macOS guest typically reports **x86_64 (Intel)** even if your host is ARM.  
  `setup.sh` auto-detects the guest architecture and downloads the correct builds:  
  - ChromeDriver: `mac-x64` or `mac-arm64`  
  - Firefox/Geckodriver: `macos` or `macos-aarch64`  
  If you see `Bad CPU type in executable`, you installed the wrong architecture—rerun `setup.sh` or replace the binary (e.g., use `mac-x64` on Intel).
