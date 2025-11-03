import unittest
from fastapi.testclient import TestClient
from domain_maintainer import app

class TestDomainMaintainer(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def test_get_domains(self):
        """Test the /get_domains/ endpoint with real data."""
        response = self.client.get("/get_domains/", params={"attributes": ["video", "audio"]})
        self.assertEqual(200, response.status_code)
        data = response.json()

        # Check that the response contains the requested attributes
        self.assertIn("video", data)
        self.assertIn("audio", data)

        # Check that the values are lists of strings (domains)
        self.assertIsInstance(data["video"], list)
        self.assertIsInstance(data["audio"], list)

        # Optionally, check if the lists are not empty and contain strings
        if data["video"]:
            self.assertIsInstance(data["video"][0], str)
        if data["audio"]:
            self.assertIsInstance(data["audio"][0], str)

if __name__ == '__main__':
    unittest.main()
