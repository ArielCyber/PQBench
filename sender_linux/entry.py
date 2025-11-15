import logging
import os
import sys

from flask import Flask, request, jsonify

from browser_manager import BrowserLaunchError
from attributes.video_sender import VideoSender

app = Flask(__name__)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)])


@app.get("/health")
def health():
    """
    Health check, if the service is alive returns ok with 200 code
    """
    return "ok", 200


@app.route('/')
def root():
    """
    Serve the main static HTML page.

    Returns
    -------
    Response
        The contents of 'mlkem_page.html' from the static folder.
    """
    algo_mode = os.getenv("MODE")
    logging.debug(f"ALGO MODE is {algo_mode}")
    if algo_mode == "KYBER":
        logging.debug("Returning kyber html")
        return app.send_static_file('kyber_page.html')
    elif algo_mode == "MLKEM":
        logging.debug("Returning mlkem html")
        return app.send_static_file('mlkem_page.html')
    return None


@app.route('/execute', methods=['POST'])
def config_handler():
    """
    Flask endpoint to initiate a PQClass session based on client config.

    Parses JSON payload, validates inputs, runs `process_session`, and returns JSON result.

    Returns
    -------
    Response
        JSON response with either `status` and `directory` on success,
        or `error` message with appropriate HTTP status code.
    """
    logging.info("Starting PQBench session...")
    data = request.get_json() or request.form
    try:
        browser = data['browser']
        logging.debug(f"Browser: {browser}")
        algo = int(data['algorithm'])
        logging.debug(f"Algo: {algo}")
        amount = int(data['sessions'])
        logging.debug(f"Amount: {amount}")
        domain = data.get('domain', 'israelhayom.co.il/you-may-find-interesting/article/17184917')
        logging.debug(f"Domain: {domain}")
        attribute = data.get('attribute')
        logging.debug(f"Attribute: {attribute}")
    except (KeyError, ValueError) as e:
        logging.error(f"Bad request: {e}")
        return jsonify({'Error': f'Bad request: {e}'}), 400

    if amount <= 0:
        logging.error("Sessions count must be greater than 0.")
        return jsonify('Error: session count must be a positive number')

    try:
        if attribute.lower() == "video":
            sender = VideoSender(browser, algo, amount, domain)
        sender = VideoSender(browser, algo, amount, domain)
        sender.run()
        return "done", 200
    except BrowserLaunchError as e:
        result = jsonify({'Error': str(e)}), 500
        logging.error(f"{e}")
        return result
    except Exception as e:
        app.logger.exception(e)
        logging.error(f"{e}")
        return jsonify({'Error': f'Unexpected server error: {e}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
