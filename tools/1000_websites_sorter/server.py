import logging

from flask import Flask, request, jsonify
import asyncio
from config import logger
from core import AutomationEngine

app = Flask(__name__)


@app.route('/execute', methods=['POST'])
def config_handler():
    logging.info("Starting session...")
    data = request.get_json() or request.form

    domain = data.get('domain', 'example.com')
    attribute = data.get('attribute', 'browser')
    button_text = data.get('button_text')

    def run_process():
        engine = AutomationEngine(domain, attribute, button_text)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(engine.run())
        loop.close()

    try:
        run_process()
        return jsonify({
            'status': 'Session completed',
            'domain': domain,
            'attribute': attribute
        })
    except Exception as e:
        return jsonify({'Error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)