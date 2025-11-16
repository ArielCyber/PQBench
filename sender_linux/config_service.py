import logging
import requests
import tldextract
from typing import Dict, Optional
import backoff
import os


class ConfigService:
    """
    Handles fetching configuration from the external domain_maintainer service.
    Its single responsibility is external data retrieval.
    """

    def __init__(self, base_url: str = None):
        # Read from env var, with a fallback for convenience
        self.base_url = base_url if base_url else os.environ.get("CONFIG_SERVICE_URL", "http://domain_maintainer:5010")
        self.logger = logging.getLogger(self.__class__.__name__)

    # This decorator will automatically retry the function
    # 3 times, with a 5-second wait, if it fails
    @backoff.on_exception(backoff.expo, (requests.exceptions.RequestException,
                                         requests.exceptions.HTTPError), max_tries=3, max_time=60)
    def get_button_values(self, website_url: str, attribute: str) -> Optional[Dict[str, str]]:
        """Fetches button values from the external service using tldextract."""
        if not website_url or not attribute:
            self.logger.error("Domain/attribute must be set to fetch button values.")
            return None

        try:
            extracted = tldextract.extract(website_url)
            domain = f"{extracted.domain}.{extracted.suffix}"
            if not extracted.domain:
                domain = extracted.subdomain if extracted.subdomain else website_url
        except Exception as e:
            self.logger.error(f"Could not parse domain from {website_url}: {e}")
            return None

        endpoint = f"{self.base_url}/get_button_by_domain/"
        params = {"domain": domain, "attribute": attribute}
        self.logger.info(f"Fetching button values for domain '{domain}'...")

        try:
            response = requests.get(endpoint, params=params, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            self.logger.warning(f"Domain '{domain}' not found. (HTTP {e.response.status_code})")
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Connection error fetching button values: {e}")
        except ValueError:
            self.logger.error("Error: Failed to decode JSON response.")

        return None
