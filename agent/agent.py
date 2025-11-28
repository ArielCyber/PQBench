import json
import logging
import os
import time

import requests
from flask import Flask, request, jsonify

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


def send_config_to_switcher(framework_config):
    """
    Forwards *one* configuration received from the framework to the switcher.
    """
    logging.info(f"Forwarding config to switcher:")
    logging.debug(json.dumps(framework_config, indent=2))

    save_config_to_file(framework_config)

    try:
        # Send the config we received from the framework to the switcher
        response = requests.post(ENTRY_CONTROLLER_URL, json=framework_config, timeout=10)
        logging.info(f"Switcher response: {response.status_code}")

        try:
            switcher_json = response.json()
        except requests.exceptions.JSONDecodeError:
            switcher_json = response.text

        # Return a success response
        return {"status": "success", "message": "Config forwarded to switcher",
                "switcher_response": switcher_json}, response.status_code

    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send config to switcher: {e}")
        # Return an error response
        return {"status": "error", "message": f"Failed to reach switcher: {e}"}, 502
    except Exception as e:
        logging.error(f"General error in send_config_to_switcher: {e}")
        return {"status": "error", "message": str(e)}, 500


@app.route('/run_experiment', methods=['POST'])
def handle_experiment_request():
    """
    This is the endpoint that the general framework will POST to.
    It receives a LIST of experiment JSONs and forwards them
    to the switcher *one by one*.
    """

    experiments_list = request.get_json()

    if not isinstance(experiments_list, list) or not experiments_list:
        logging.warning("Request received with no JSON list payload.")
        return jsonify({"error": "Payload must be a non-empty list (array) of experiment objects."}), 400

    logging.info(f"Received a batch of {len(experiments_list)} experiments from the framework. Starting to process...")

    results = []

    for i, experiment_config in enumerate(experiments_list):

        logging.info(f"--- Sending experiment {i + 1}/{len(experiments_list)} to switcher... ---")

        if not isinstance(experiment_config, dict):
            logging.warning(f"Item {i} in list is not a valid JSON object, skipping.")
            results.append({
                "experiment_index": i,
                "status": "error",
                "message": "Item was not a valid experiment object (dictionary)."
            })
            continue

        status_message, status_code = send_config_to_switcher(experiment_config)

        results.append({
            "experiment_index": i,
            "config_sent": experiment_config,
            "switcher_response": status_message
        })

        time.sleep(1)

    logging.info("Finished processing batch.")
    return jsonify({
        "batch_summary": "All experiments in the batch have been processed.",
        "total_received": len(experiments_list),
        "results": results
    }), 200


@app.route('/health')
def health():
    return "ok", 200


if __name__ == "__main__":
    print("Agent is running as a SERVER, waiting for POST requests from the framework on http://0.0.0.0:5000/run_experiment ...")
    app.run(host="0.0.0.0", port=5000)




