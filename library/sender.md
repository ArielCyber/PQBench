# PQBench Sender Service

This service is responsible for generating data traffic with specific URLs using various Post-Quantum Cryptography (PQC) algorithms. The environment runs in a containerized setup (QEMU).

## Supported Configurations

**Browsers:**
* Chrome
* Firefox

**Algorithms:**
* **0:** Non-PQC (Standard X25519)
* **1:** X25519Kyber768
* **2:** X25519ML-KEM768

---

## Usage (Input Configuration)

The service accepts a JSON payload to configure the traffic generation.

**Parameters:**
* `browser`: Target browser (`chrome` or `firefox`).
* `algorithm`: Integer mapping to the supported algorithms (see above).
* `sessions`: Integer representing the number of sessions.
* `domain`: The target URL or domain name.

**Example Payload:**
```json
{
  "browser": "chrome",
  "algorithm": 1,
  "sessions": 10,
  "domain": "example.com"
}
```

---

## Windows Setup

### 1. Automatic Installation (Default)
When the container starts, it checks for an existing Windows installation. If none is found, it will automatically:
1.  Download the desired Windows version.
2.  Install the OS.
3.  Run the `install.bat` script located in the `oem` folder.

### 2. Manual Execution (Troubleshooting)
If the automatic process fails, you can trigger the installation manually via the terminal:

```powershell
cd C:\oem
.\install.bat
```

> **⚠️ Important Note regarding Fonts:**
> The Windows installation includes a specific font folder. **Do not delete this folder.** These fonts are required for Chrome to run correctly within this environment.

---

## macOS Setup

### 1. Initial Container Start
When the container starts for the first time, it will automatically download the required macOS version. Once the download is complete, open the QEMU interface in your browser.
* **Default Ports:** `8007` or `8008`

### 2. OS Installation
1.  **Disk Setup:** Select **Disk Utility**. Choose the largest disk (out of the 3 options), click **Erase**, and assign a name to the disk. Close Disk Utility.
2.  **Install macOS:** Return to the main screen and select **Reinstall macOS**.
3.  **Setup Wizard:** Follow the prompts. When asked for region, language, or analytics, **opt out of all features** and select the most basic options to speed up the process.

### 3. Post-Installation Configuration
Once the OS has booted, open the Terminal and mount the shared directory:

```bash
sudo -S mount_9p shared
cd /Volumes/shared
```

### 4. Running the Sender
Execute one of the following scripts depending on your algorithm requirement:

```bash
./run_kyber.sh
# OR
./run_mlkem.sh
```

**Notes on Execution:**
* **Xcode:** Press `Enter` if prompted to allow the Xcode download. This may take some time.
* **Sudo Privileges:** You may be prompted for your password multiple times. If the script times out or you miss a prompt, simply run the script file again.

### 5. Verification
When the script finishes successfully, the sender will listen on **port 5000**.
To verify, open **Safari** inside the VM and navigate to:
`http://localhost:5000`


## Additional Notes

* When making any changes to any *.sh file, make sure to run `dos2unix filename.sh`
to make sure there aren't any invisible non Unix characters!