from abc import ABC, abstractmethod
from selenium import webdriver
import undetected_chromedriver as uc


class AlgoStrategy(ABC):
    """Abstract base class for browser algorithm configuration."""

    @abstractmethod
    def apply_firefox_options(self, options: webdriver.FirefoxOptions):
        """Applies specific preferences to Firefox options."""
        pass

    @abstractmethod
    def apply_chrome_options(self, options: uc.ChromeOptions, prefs: dict):
        """Applies specific preferences to Chrome options and localState."""
        pass


class NonPQCStrategy(AlgoStrategy):
    def apply_firefox_options(self, options):
        options.set_preference('network.http.http3.enable_kyber', False)
        options.set_preference('security.tls.enable_kyber', False)

    def apply_chrome_options(self, options, prefs):
        prefs["browser"]["enabled_labs_experiments"] = [
            "enable-tls13-kyber@2",
            "use-ml-kem@2"
        ]


class KyberStrategy(AlgoStrategy):
    def apply_firefox_options(self, options):
        options.set_preference("security.tls.enable_kyber", True)
        options.set_preference("network.http.http3.enabled", True)
        options.set_preference("network.http.http3.enable_kyber", True)

    def apply_chrome_options(self, options, prefs):
        prefs["browser"]["enabled_labs_experiments"] = ["use-ml-kem@2"]


class MLKEMStrategy(AlgoStrategy):
    def apply_firefox_options(self, options):
        options.set_preference("security.tls.enable_kyber", True)
        options.set_preference("network.http.http3.enabled", True)
        options.set_preference("network.http.http3.enable_kyber", True)

    def apply_chrome_options(self, options, prefs):
        prefs["browser"]["enabled_labs_experiments"] = [
            "enable-tls13-kyber@2",  # Disabled
            "use-ml-kem@1",  # Enabled
        ]


# Simple factory for the strategies
def get_algo_strategy(algo_id: int) -> AlgoStrategy:
    strategies = {
        0: NonPQCStrategy(),
        1: KyberStrategy(),
        2: MLKEMStrategy()
    }
    return strategies.get(algo_id, NonPQCStrategy())  # Default to NonPQC