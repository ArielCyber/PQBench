import unittest
import os
import subprocess
import types
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, call

# Use FastAPI's TestClient for testing the routes
from fastapi.testclient import TestClient

# Import the app and functions from your sniffer.py file
try:
    # Need to import sessions for type hints in sniffer.py
    # We can mock it if it's not a real file
    try:
        import sessions
    except ImportError:
        sessions = MagicMock()
        sessions.StartBatchRequest = dict
        sessions.DoneRequest = dict

    from sniffer import app, name_dir, _and_ports, _build_domain_bpf, _resolve_domain_ips, _split_streams_tshark
    import sniffer  # Import the full module to patch socket
except ImportError as e:
    print(f"Error: Make sure your sniffer.py file is in the same directory. {e}")
    exit(1)


class TestSnifferApp(unittest.TestCase):
    """
    Test suite for the sniffer.py FastAPI application and helper functions.
    """

    def setUp(self):
        """
        Set up the TestClient for the FastAPI app.
        This runs before each test.
        """
        self.client = TestClient(app)
        # Clear session state between tests
        sniffer._sessions = {}
        sniffer._stop_events = {}

    # --- Test Helper Functions (Converted from pytest) ---

    def test_name_dir_valid(self):
        self.assertEqual(name_dir("linux", "chrome", 2), "122")
        self.assertEqual(name_dir("windows", "firefox", 1), "211")
        self.assertEqual(name_dir("macos", "chrome", 0), "320")

    def test_name_dir_invalid_os(self):
        with self.assertRaises(ValueError):
            name_dir("solaris", "chrome", 1)

    def test_name_dir_invalid_browser(self):
        with self.assertRaises(ValueError):
            name_dir("linux", "opera", 1)

    def test_and_ports_none(self):
        self.assertEqual(_and_ports("(ip or ip6)", None), "(ip or ip6)")

    def test_and_ports_single(self):
        out = _and_ports("(ip)", "443")
        self.assertEqual(out, "((ip)) and (tcp port 443)")

    def test_and_ports_multi(self):
        out = _and_ports("(ip)", "443,80,  8443")
        self.assertEqual(out, "((ip)) and ((tcp port 443) or (tcp port 80) or (tcp port 8443))")

    def test_and_ports_ignores_bad_tokens(self):
        out = _and_ports("(ip)", "443,foo,bar, 80")
        self.assertEqual(out, "((ip)) and ((tcp port 443) or (tcp port 80))")

    def test_build_domain_bpf_with_ips(self):
        bpf = _build_domain_bpf(
            "10.0.0.5",
            ["1.1.1.1", "9.9.9.9"],
            ["2606:4700:4700::1111"]
        )
        self.assertTrue(bpf.startswith("(host 10.0.0.5) and ("))
        self.assertIn("ip and ((dst host 1.1.1.1 or src host 1.1.1.1) or (dst host 9.9.9.9 or src host 9.9.9.9))", bpf)
        self.assertIn("ip6 and ((dst host 2606:4700:4700::1111 or src host 2606:4700:4700::1111))", bpf)

    def test_build_domain_bpf_fallback_when_empty(self):
        bpf = _build_domain_bpf("10.0.0.5", [], [])
        self.assertEqual(bpf, "(host 10.0.0.5) and (ip or ip6)")

    @patch('sniffer.socket.getaddrinfo')
    def test_resolve_domain_ips_success(self, mock_getaddrinfo):
        def fake_getaddrinfo(host, *_args, **_kwargs):
            return [
                (sniffer.socket.AF_INET, None, None, None, ("1.2.3.4", 0)),
                (sniffer.socket.AF_INET6, None, None, None, ("2001:db8::1", 0, 0, 0)),
                (sniffer.socket.AF_INET, None, None, None, ("5.6.7.8", 0)),
            ]

        mock_getaddrinfo.side_effect = fake_getaddrinfo
        v4, v6 = _resolve_domain_ips("example.com")
        self.assertEqual(v4, ["1.2.3.4", "5.6.7.8"])
        self.assertEqual(v6, ["2001:db8::1"])

    @patch('sniffer.socket.getaddrinfo', side_effect=OSError("dns failure"))
    def test_resolve_domain_ips_failure(self, mock_getaddrinfo):
        v4, v6 = _resolve_domain_ips("example.com")
        self.assertEqual(v4, [])
        self.assertEqual(v6, [])

    @patch('subprocess.run')
    @patch('subprocess.check_output', side_effect=FileNotFoundError("tshark not found"))
    @patch('sniffer.which', return_value=None)
    def test_split_streams_tshark_no_tshark(self, mock_which, mock_check_output, mock_run):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_pcap = Path(tmpdir) / "in.pcap"
            input_pcap.write_bytes(b"")
            _split_streams_tshark(str(input_pcap), str(Path(tmpdir) / "streams"), "121", "timestamp")
            mock_run.assert_not_called()
            # check_output is called by _split_streams_tshark, but which() stops it
            mock_which.assert_called_with("tshark")
            mock_check_output.assert_not_called()

    @patch('subprocess.run')
    @patch('subprocess.check_output')
    @patch('sniffer.which', return_value='/usr/bin/tshark')
    def test_split_streams_tshark_happy(self, mock_which, mock_check_output, mock_run):

        # Mock the different tshark calls
        def fake_check_output(cmd, text=True):
            cmd_str = " ".join(cmd)
            if "tls.handshake.type==1" in cmd_str:
                return "1\n\n2\n1\n"  # Find streams 1 and 2
            # Check for the specific packet count command
            if "tcp.stream==1" in cmd_str and "-e" in cmd_str and "frame.number" in cmd_str:
                return "frame\n" * 40  # Stream 1 has 40 packets
            if "tcp.stream==2" in cmd_str and "-e" in cmd_str and "frame.number" in cmd_str:
                return "frame\n" * 10  # Stream 2 has 10 packets (too few)
            return ""

        mock_check_output.side_effect = fake_check_output

        # Mock subprocess.run to succeed for ServerHello, AppData, and extraction
        mock_run.return_value = types.SimpleNamespace(returncode=0)

        calls = []

        def fake_run_capture(cmd, **kwargs):
            calls.append(cmd)
            return types.SimpleNamespace(returncode=0)

        mock_run.side_effect = fake_run_capture

        with tempfile.TemporaryDirectory() as tmpdir:
            input_pcap = Path(tmpdir) / "in.pcap"
            input_pcap.write_bytes(b"\xd4\xc3\xb2\xa1")
            outdir = Path(tmpdir) / "streams"

            _split_streams_tshark(
                str(input_pcap),
                str(outdir),
                "121",
                "timestamp",
                min_packets=30  # Set min packets to 30
            )

            # Check that tshark was found
            mock_which.assert_called_with("tshark")

            # Should have kept stream 1 (40 packets) and dropped stream 2 (10 packets)
            kept_stream_1 = False
            extracted_stream_2 = False
            for cmd in calls:
                cmd_str = " ".join(cmd)
                if "tcp.stream==1" in cmd_str and "-w" in cmd_str:
                    kept_stream_1 = True
                if "tcp.stream==2" in cmd_str and "-w" in cmd_str:
                    extracted_stream_2 = True

            self.assertTrue(kept_stream_1, "Stream 1 (40 packets) was not extracted")
            self.assertFalse(extracted_stream_2, "Stream 2 (10 packets) was extracted but should have been dropped")

    # --- Test FastAPI Routes ---

    def test_health_route(self):
        response = self.client.get("/health")
        self.assertEqual(response.json(), ["ok", 200])

    @patch('sniffer.get_if_list', return_value=["lo", "eth0"])
    def test_ifaces_route(self, mock_get_if_list):
        response = self.client.get("/ifaces")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), ["lo", "eth0"])

    def test_status_route_empty(self):
        response = self.client.get("/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"sessions": []})

    def test_done_route_missing_params(self):
        # FIX: App returns 400, not 422, based on internal logic
        response = self.client.post("/done", json={"foo": "bar"})
        self.assertEqual(response.status_code, 400)  # App raises 400 before Pydantic

    @patch('sniffer.socket.gethostbyname', return_value="1.2.3.4")
    def test_done_route_by_url(self, mock_gethostbyname):
        response = self.client.post("/done", json={"url": "http://example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["container_ip"], "1.2.3.4")
        self.assertEqual(response.json()["stopped_session_ids"], [])

    def test_done_route_stops_session(self):
        # FIX: Set up mocks *inside* the test, after setUp() has run
        mock_event = MagicMock(is_set=MagicMock(return_value=False))
        sniffer._sessions["test_sid"] = MagicMock(container_ip="1.2.3.4", done=False)
        sniffer._stop_events["test_sid"] = mock_event

        response = self.client.post("/done", json={"container_ip": "1.2.3.4"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stopped_session_ids"], ["test_sid"])
        mock_event.set.assert_called_once()

    def test_start_batch_empty_targets(self):
        response = self.client.post("/start", json={"targets": []})
        self.assertEqual(response.status_code, 400)
        self.assertIn("targets must be non-empty", response.json()["detail"])

    @patch('sniffer.get_if_list', return_value=["lo", "eth0"])
    def test_start_batch_bad_iface(self, mock_get_if_list):
        payload = {
            "targets": [{
                "os": "linux", "browser": "chrome", "algo": 1,
                "container_ip": "1.2.3.4", "iface": "bad-iface",
                "filter_mode": "none", "duration_sec": 10
            }]
        }
        response = self.client.post("/start", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("iface 'bad-iface' not found", response.json()["detail"])

    @patch('threading.Thread')
    @patch('sniffer.Event')
    @patch('os.makedirs')
    @patch('sniffer.get_if_list', return_value=["lo", "eth0"])
    @patch('sniffer._resolve_domain_ips', return_value=(["1.1.1.1"], []))
    def test_start_batch_success(self, mock_resolve, mock_get_if, mock_makedirs, mock_event, mock_thread):
        # Mock the 'armed' event to fire immediately
        mock_armed_event = MagicMock()
        mock_armed_event.wait.return_value = True
        mock_event.return_value = mock_armed_event

        # Mock the thread
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance

        payload = {
            "targets": [{
                "os": "linux", "browser": "chrome", "algo": 1,
                "container_ip": "1.2.3.4", "iface": "eth0",
                "filter_mode": "domain", "domain": "example.com",
                "ports": "443",
                "duration_sec": 10
            }]
        }
        response = self.client.post("/start", json=payload)

        # Check response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["started"])
        self.assertEqual(len(data["children"]), 1)
        child = data["children"][0]
        self.assertEqual(child["container_ip"], "1.2.3.4")
        self.assertEqual(child["code"], "121")
        self.assertIn("fake-bpf", child["bpf"])  # Our _build_domain_bpf mock
        self.assertIn("443", child["bpf"])  # Our _and_ports mock

        # Check that state was updated
        self.assertEqual(len(sniffer._sessions), 1)
        self.assertEqual(len(sniffer._stop_events), 1)

        # Check that thread was started
        mock_thread.assert_called_once()
        mock_thread_instance.start.assert_called_once()
        mock_armed_event.wait.assert_called_once()


if __name__ == '__main__':
    # Patch the BPF functions for the main test run
    # This avoids real DNS lookups or complex BPF logic
    with patch('sniffer._build_domain_bpf', return_value="fake-bpf"):
        with patch('sniffer._and_ports', side_effect=lambda bpf, ports: f"({bpf}) and (ports: {ports})"):
            unittest.main()

