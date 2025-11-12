import unittest
import os
import json
from unittest.mock import patch, MagicMock, call

# Import the Flask app and functions from your main.py file
# We assume the file is named 'main.py'
try:
    from main import app, process_session, open_browser, open_firefox, open_chrome, BrowserLaunchError
except ImportError:
    print("Error: Make sure your main.py file is in the same directory.")
    exit(1)


class TestProcessorApp(unittest.TestCase):
    """
    Test suite for the main.py Flask application and helper functions.
    """

    def setUp(self):
        """
        Set up the test client for the Flask app.
        This runs before each test.
        """
        app.config['TESTING'] = True
        self.client = app.test_client()

    # --- Test Flask Routes ---

    def test_health_check(self):
        """
        Test the /health endpoint.
        """
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.decode(), 'ok')

    @patch('processor.app.send_static_file')
    @patch.dict(os.environ, {"MODE": "MLKEM"})
    def test_root_route_mlkem(self, mock_send_file):
        """
        Test the root route '/' when MODE is MLKEM.
        """
        mock_send_file.return_value = "mlkem_page"
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        mock_send_file.assert_called_once_with('mlkem_page.html')

    @patch('processor.app.send_static_file')
    @patch.dict(os.environ, {"MODE": "KYBER"})
    def test_root_route_kyber(self, mock_send_file):
        """
        Test the root route '/' when MODE is KYBER.
        """
        mock_send_file.return_value = "kyber_page"
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        mock_send_file.assert_called_once_with('kyber_page.html')

    @patch.dict(os.environ, {"MODE": "OTHER"})
    def test_root_route_other(self):
        """
        Test the root route '/' when MODE is not set or is unknown.
        Flask will raise a TypeError because the view returns None,
        and app.config['TESTING'] is True.
        """
        # We assert that a TypeError is raised because the view returns None
        with self.assertRaises(TypeError):
            self.client.get('/')

    # --- Test /execute Endpoint ---

    @patch('processor.process_session')
    def test_execute_handler_success(self, mock_process_session):
        """
        Test the /execute endpoint with a valid request (happy path).
        """
        mock_process_session.return_value = {"status": "mocked_done"}
        payload = {
            "browser": "chrome",
            "algorithm": 2,
            "sessions": 1,
            "domain": "test.com"
        }
        response = self.client.post('/execute', json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "mocked_done"})
        # Verify process_session was called with the correct arguments
        mock_process_session.assert_called_once_with("chrome", 2, 1, "test.com")

    def test_execute_handler_missing_key(self):
        """
        Test /execute with a missing key in the JSON payload.
        """
        payload = {"algorithm": 2, "sessions": 1}  # Missing "browser"
        response = self.client.post('/execute', json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Error", response.json)
        self.assertIn("Bad request", response.json.get("Error", ""))

    def test_execute_handler_bad_value_type(self):
        """
        Test /execute with a bad value type (e.g., string for 'sessions').
        """
        payload = {
            "browser": "chrome",
            "algorithm": 2,
            "sessions": "one"  # Should be an int
        }
        response = self.client.post('/execute', json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Error", response.json)
        self.assertIn("Bad request", response.json.get("Error", ""))

    def test_execute_handler_zero_sessions(self):
        """
        Test /execute with 0 sessions.
        Note: The original code returns a 200 status for this,
        though a 400 might be more appropriate. We test the existing behavior.
        """
        payload = {
            "browser": "chrome",
            "algorithm": 2,
            "sessions": 0  # Invalid amount
        }
        response = self.client.post('/execute', json=payload)
        # This could ideally be a 400, but we test the code as-is
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, 'Error: session count must be a positive number')

    @patch('processor.process_session')
    def test_execute_handler_browser_launch_error(self, mock_process_session):
        """
        Test /execute when process_session raises a BrowserLaunchError.
        """
        mock_process_session.side_effect = BrowserLaunchError("Test launch fail")
        payload = {"browser": "chrome", "algorithm": 2, "sessions": 1}
        response = self.client.post('/execute', json=payload)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json, {'Error': 'Test launch fail'})

    @patch('processor.process_session')
    def test_execute_handler_generic_error(self, mock_process_session):
        """
        Test /execute when process_session raises an unexpected Exception.
        """
        mock_process_session.side_effect = Exception("Test generic fail")
        payload = {"browser": "chrome", "algorithm": 2, "sessions": 1}
        response = self.client.post('/execute', json=payload)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json, {'Error': 'Unexpected server error'})

    # --- Test Helper Functions ---

    @patch('processor.open_chrome')
    @patch('processor.open_firefox')
    def test_open_browser_dispatcher(self, mock_open_firefox, mock_open_chrome):
        """
        Test the open_browser function to ensure it calls the correct
        browser-specific function based on input.
        """
        # Test Chrome
        open_browser("chrome", 1)
        mock_open_chrome.assert_called_once_with(1)
        mock_open_firefox.assert_not_called()

        # Reset mocks
        mock_open_chrome.reset_mock()
        mock_open_firefox.reset_mock()

        # Test Firefox (and case-insensitivity)
        open_browser("FIREFOX", 2)
        mock_open_chrome.assert_not_called()
        mock_open_firefox.assert_called_once_with(2)

    # We patch the webdriver and driver managers for the next tests
    @patch('processor.webdriver.Firefox')
    @patch('processor.FirefoxService')
    @patch('processor.GeckoDriverManager')
    def test_open_firefox_options(self, mock_gecko_manager, mock_service, mock_firefox_driver):
        """
        Test that open_firefox sets the correct preferences for each algorithm.
        """
        mock_gecko_instance = mock_gecko_manager.return_value
        mock_gecko_instance.install.return_value = '/fake/gecko/path'

        # Test algo 0 (non-PQC)
        open_firefox(0)
        args, kwargs = mock_firefox_driver.call_args
        options = kwargs['options']
        # Access the internal _preferences dict instead of non-existent get_preference()
        self.assertEqual(options._preferences['security.tls.enable_kyber'], False)
        self.assertEqual(options._preferences['network.http.http3.enable_kyber'], False)
        self.assertIn('-headless', options.arguments)

        # Test algo 1 (Kyber)
        open_firefox(1)
        args, kwargs = mock_firefox_driver.call_args
        options = kwargs['options']
        self.assertEqual(options._preferences['security.tls.enable_kyber'], True)
        self.assertEqual(options._preferences['network.http.http3.enable_kyber'], True)

        # Test algo 2 (MLKEM)
        open_firefox(2)
        args, kwargs = mock_firefox_driver.call_args
        options = kwargs['options']
        self.assertEqual(options._preferences['security.tls.enable_kyber'], True)
        self.assertEqual(options._preferences['network.http.http3.enable_kyber'], True)

    @patch('processor.webdriver.Chrome')
    @patch('processor.ChromeService')
    @patch.dict(os.environ, {"CHROMEDRIVER_PATH": "/fake/chrome/path"})
    def test_open_chrome_options(self, mock_service, mock_chrome_driver):
        """
        Test that open_chrome sets the correct experimental options for each algorithm.
        """
        # Test algo 0 (non-PQC)
        open_chrome(0)
        args, kwargs = mock_chrome_driver.call_args
        options = kwargs['options']
        prefs = options.experimental_options.get('localState', {}).get('browser', {})
        self.assertIn("enable-tls13-kyber@2", prefs["enabled_labs_experiments"])
        self.assertIn("use-ml-kem@2", prefs["enabled_labs_experiments"])
        self.assertIn('--headless=new', options.arguments)

        # Test algo 1 (Kyber)
        open_chrome(1)
        args, kwargs = mock_chrome_driver.call_args
        options = kwargs['options']
        prefs = options.experimental_options.get('localState', {}).get('browser', {})
        self.assertNotIn("enable-tls13-kyber@2", prefs.get("enabled_labs_experiments", []))
        self.assertIn("use-ml-kem@2", prefs["enabled_labs_experiments"])

        # Test algo 2 (MLKEM)
        open_chrome(2)
        args, kwargs = mock_chrome_driver.call_args
        options = kwargs['options']
        prefs = options.experimental_options.get('localState', {}).get('browser', {})
        self.assertIn("enable-tls13-kyber@2", prefs["enabled_labs_experiments"])
        self.assertIn("use-ml-kem@1", prefs["enabled_labs_experiments"])

    @patch('processor.open_browser')
    @patch('processor.WebDriverWait')
    @patch('processor.time.sleep')
    def test_process_session(self, mock_sleep, mock_wait, mock_open_browser):
        """
        Test the process_session logic to ensure it loops correctly
        and calls the driver methods as expected.
        """
        mock_driver = MagicMock()
        mock_open_browser.return_value = mock_driver
        mock_wait_instance = mock_wait.return_value
        mock_wait_instance.until.return_value = True  # Simulate wait succeeding

        amount = 3
        domain = "process.test"

        # Run the function
        result = process_session("firefox", 1, amount, domain)

        # Check results
        self.assertEqual(result, {"status": "done"})

        # Check that functions were called the correct number of times
        self.assertEqual(mock_open_browser.call_count, amount)
        self.assertEqual(mock_driver.get.call_count, amount)
        self.assertEqual(mock_wait.call_count, amount)
        self.assertEqual(mock_sleep.call_count, amount)
        self.assertEqual(mock_driver.quit.call_count, amount)

        # Check that the calls were made with the correct arguments
        mock_open_browser.assert_called_with("firefox", 1)  # Checks the last call
        mock_driver.get.assert_called_with(f'https://{domain}')  # Checks the last call


if __name__ == '__main__':
    unittest.main()

