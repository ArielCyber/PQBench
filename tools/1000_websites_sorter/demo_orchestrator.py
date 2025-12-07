import asyncio
import logging
import os
import re
import socket
import pandas as pd
from urllib.parse import urlparse
from scapy.all import AsyncSniffer, wrpcap
from datetime import datetime

# Import the actual automation engine from your local files
# Ensure core.py, strategies.py, scanner.py, cursor.py, config.py are in the same folder
from core import AutomationEngine

# --- CONFIGURATION ---
EXCEL_FILE = 'domain_data.xlsx'
OUTPUT_DIR = 'local_recordings'
# You can adjust which attributes you want to run here
ATTRIBUTES_TO_TEST = ['video', 'audio', 'game', 'map', 'cloud', 'download', 'rtt', 'browser']

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - ORCHESTRATOR - %(message)s'
)
logger = logging.getLogger(__name__)


# --- 1. MAINTAINER LOGIC (Updated Indices) ---
def load_domains_from_excel(attributes):
    """
    Reads Excel based on the structure:
    Column 0: Button Text
    Column 1: Domain
    Row 0: Header (skipped by header=0)
    """
    jobs = []

    if not os.path.exists(EXCEL_FILE):
        logger.error(f"Excel file not found: {EXCEL_FILE}")
        return []

    for attr in attributes:
        try:
            # Read sheet, treating first row (0) as header
            df = pd.read_excel(EXCEL_FILE, sheet_name=attr, header=0)

            for index, row in df.iterrows():
                try:
                    # Column 0: Button Text (might be NaN/empty)
                    raw_btn = row.iloc[0]
                    button = str(raw_btn).strip() if pd.notna(raw_btn) else None

                    # Column 1: Domain
                    if len(row) > 1:
                        raw_dom = row.iloc[1]
                        domain = str(raw_dom).strip() if pd.notna(raw_dom) else None
                    else:
                        domain = None

                    if domain:
                        jobs.append({
                            "domain": domain,
                            "attribute": attr,
                            "button": button
                        })
                except Exception as row_err:
                    logger.warning(f"Skipping malformed row in '{attr}': {row_err}")

        except Exception as e:
            # Sheet might not exist, or file error
            logger.warning(f"Could not read attribute '{attr}' (sheet might be missing): {e}")

    return jobs


# --- 2. SNIFFER LOGIC ---
class LocalSniffer:
    def __init__(self, domain, attribute, output_folder):
        self.domain = domain
        self.attribute = attribute
        self.output_folder = output_folder
        self.sniffer = None
        self.outfile = None

    def _resolve_ip(self, url):
        try:
            if not url.startswith("http"):
                url = f"https://{url}"
            hostname = urlparse(url).hostname
            return socket.gethostbyname(hostname)
        except:
            return None

    def start(self):
        # 1. Strip Query String (remove everything after ?)
        clean_url = self.domain.split('?')[0]

        # 2. Replace ALL invalid filesystem characters with underscores
        # Allows: alphanumeric, underscore, dash, dot. Everything else becomes '_'
        safe_domain = re.sub(r'[^\w\-_\.]', '_', clean_url)

        # Limit length to prevent OS errors (max 255 usually)
        if len(safe_domain) > 100:
            safe_domain = safe_domain[:100]

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{self.attribute}_{safe_domain}_{timestamp}.pcap"
        self.outfile = os.path.join(self.output_folder, filename)

        # IP Filter
        target_ip = self._resolve_ip(self.domain)
        bpf_filter = f"host {target_ip}" if target_ip else None

        if bpf_filter:
            logger.info(f"Sniffer armed for IP: {target_ip} ({self.domain}) -> {filename}")
        else:
            logger.warning(f"Could not resolve IP for {self.domain}. Capturing ALL traffic.")

        # Start Scapy
        self.sniffer = AsyncSniffer(
            filter=bpf_filter,
            store=True
        )
        self.sniffer.start()

    def stop(self):
        if self.sniffer:
            logger.info("Stopping sniffer...")
            packets = self.sniffer.stop()
            try:
                wrpcap(self.outfile, packets)
                logger.info(f"PCAP saved: {self.outfile} ({len(packets)} packets)")
            except Exception as e:
                logger.error(f"Failed to write PCAP: {e}")


# --- 3. SWITCHER / ORCHESTRATOR LOGIC ---
async def run_orchestration():
    # Setup output directory
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # 1. Get Jobs (Maintainer Logic)
    logger.info("Loading jobs from Excel...")
    jobs = load_domains_from_excel(ATTRIBUTES_TO_TEST)

    if not jobs:
        logger.error("No jobs found. Check Excel file and sheet names.")
        return

    logger.info(f"Found {len(jobs)} domains to process.")

    # 2. Iterate and Execute (Switcher Logic)
    for i, job in enumerate(jobs):
        domain = job['domain']
        attr = job['attribute']
        btn = job['button']

        logger.info(f"--- STARTING JOB {i + 1}/{len(jobs)}: {domain} [{attr}] ---")
        if btn:
            logger.info(f"Target Button for this run: '{btn}'")

        # A. Start Sniffer
        sniffer = LocalSniffer(domain, attr, OUTPUT_DIR)
        try:
            sniffer.start()
        except Exception as e:
            logger.error(f"Failed to start sniffer (Run as Admin/Root?): {e}")
            # We continue even if sniffer fails, to test the browser automation

        # B. Run Sender (AutomationEngine)
        try:
            # Initialize the engine
            engine = AutomationEngine(
                domain=domain,
                attribute=attr,
                target_button=btn
            )

            # Run the strategy (browser interaction)
            await engine.run()

        except Exception as e:
            logger.error(f"Failed to process {domain}: {e}")

        # C. Stop Sniffer
        finally:
            if sniffer:
                sniffer.stop()

        # Optional: Cool down between sites to let sockets close
        logger.info("Cooling down for 2 seconds...")
        await asyncio.sleep(2)


if __name__ == "__main__":
    # Windows: Run as Administrator
    # Linux: Run with sudo
    try:
        asyncio.run(run_orchestration())
    except KeyboardInterrupt:
        logger.info("Orchestration stopped by user.")