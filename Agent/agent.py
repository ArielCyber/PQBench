import os

import requests
import random
import json
from flask import Flask, request, jsonify, app
from datetime import datetime

app = Flask(__name__)

#temp for now(will integrate with dvir)
#ENTRY_CONTROLLER_URL = "http://localhost:5000/config"

ENTRY_CONTROLLER_URL = os.getenv("ENTRY_CONTROLLER_URL", "http://localhost:5000/config")


BLOCKS = {
    "high": range(9, 17),
    "medium": range(17, 24),
    "low": range(0, 9)
}

OPTIONS = {
    "os": ["0", "1", "2"],  # 0=Linux, 1=Windows, 2=MacOS
    "browser": ["chrome", "firefox"],
    "algorithm": ["0", "1", "2"],  # 0=Non-PQC, 1=Kyber, 2=MLKEM
    "sessions": list(range(1, 11))
}


def get_current_block():
    """
    Determines the current traffic block based on hour and weekday.

    Returns
    -------
    str
        One of 'high', 'medium', or 'low' depending on current time and weekday.
    """
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()
    if weekday == 4 or weekday == 5:
        return "low"
    for block, hours in BLOCKS.items():
        if hour in hours:
            return block
    return "low"


def generate_random_config():
    """
    Randomly selects values for OS, browser, algorithm, and session count.

    Returns
    -------
    dict
        A configuration dictionary with randomized keys:
        'os', 'browser', 'algorithm', and 'sessions'.
    """
    return {
        "os": random.choice(OPTIONS["os"]),
        "browser": random.choice(OPTIONS["browser"]),
        "algorithm": random.choice(OPTIONS["algorithm"]),
        "sessions": random.choice(OPTIONS["sessions"])
    }


def save_config_to_file(config, filename="last_sent_config.json"):
    """
    Saves a given configuration dictionary to a local JSON file.

    Parameters
    ----------
    config : dict
        The configuration to save.
    filename : str, optional
        The filename to save to (default is 'last_sent_config.json').

    Raises
    ------
    IOError
        If there is an issue writing the file.
    """
    with open(filename, "w") as f:
        json.dump(config, f, indent=4)


def send_config():
    """
    Generates a configuration, saves it to file, and sends it to the entry controller.

    Prints the configuration and server response to the console.

    Raises
    ------
    requests.exceptions.RequestException
        If the HTTP POST request fails.
    """
    block = get_current_block()
    config = generate_random_config()

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Sending to controller (block: {block}) with config:")
    print(config)

    save_config_to_file(config)

    try:
        response = requests.post(ENTRY_CONTROLLER_URL, json=config)
        print(f"Server response: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Failed to send config: {e}")


if __name__ == "__main__":
    """
    Entry point for script execution.
    Calls send_config to dispatch a randomized configuration.
    """
    #send_config()
    app.run(host="0.0.0.0", port=5000)