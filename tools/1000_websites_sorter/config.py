import os
import logging

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
UPLOAD_FILE_PATH = os.path.abspath("dummy_upload.jpeg")

# Create dummy file if not exists
if not os.path.exists(UPLOAD_FILE_PATH):
    with open(UPLOAD_FILE_PATH, "w") as f:
        f.write("Test file content.")