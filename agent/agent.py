import os
import requests
import json
from flask import Flask, request, jsonify, app
from datetime import datetime
import logging
import time

app = Flask(__name__)

# This is the internal Docker URL for the switcher
ENTRY_CONTROLLER_URL = os.getenv("ENTRY_CONTROLLER_URL", "http://switcher:5000/config")

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


def save_config_to_file(config, filename="last_sent_config.json"):
    """
    Saves a given configuration dictionary to a local JSON file for logging.
    """
    try:
        with open(filename, "w") as f:
            json.dump(config, f, indent=4)
    except IOError as e:
        logging.warning(f"Could not save config file: {e}")


def send_batch_to_switcher(batch_payload):
    save_config_to_file(batch_payload)
    try:
        response = requests.post(ENTRY_CONTROLLER_URL, json=batch_payload, timeout=300)
        
        logging.info(f"Switcher batch response code: {response.status_code}")
        try:
            switcher_resp_data = response.json()
        except:
            switcher_resp_data = response.text

        return jsonify(switcher_resp_data), response.status_code

    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send batch to switcher: {e}")
        return jsonify({"status": "error", "message": f"Failed to reach switcher: {e}"}), 502




@app.route('/run_experiment', methods=['POST'])
def handle_experiment_request():
    experiments_list = request.get_json()

    if not isinstance(experiments_list, list) or not experiments_list:
        logging.warning("Request received with no JSON list payload.")
        return jsonify({"error": "Payload must be a non-empty list (array) of experiment objects."}), 400

    logging.info(f"Received a batch of {len(experiments_list)} experiments from Bar.")
    
    batch_payload = {"jobs": experiments_list}
    return send_batch_to_switcher(batch_payload)

@app.route('/run_all', methods=['POST'])
def run_all_matrix():
    global_config = request.get_json() or {}
    sessions_count = global_config.get("sessions", 5)

    logging.info(f"Generating matrix for ALL combinations with sessions={sessions_count}...")

    os_options = ["linux", "windows", "macos"]
    browser_options = ["chrome", "firefox"]
    algo_options = ["kyber", "mlkem"] 

    generated_jobs = []

    for os_name in os_options:
        for browser in browser_options:
            for algo in algo_options:
                generated_jobs.append({
                    "os": os_name,
                    "browser": browser,
                    "algorithm": algo,
                    "sessions": sessions_count
                })

    full_payload = {"jobs": generated_jobs}
    return send_batch_to_switcher(full_payload)
        

@app.route('/health')
def health():
    return "ok", 200


if __name__ == "__main__":
    print("Agent is running as a SERVER, waiting for POST requests from Bar on http://0.0.0.0:5000/run_experiment ...")
    app.run(host="0.0.0.0", port=5000)
