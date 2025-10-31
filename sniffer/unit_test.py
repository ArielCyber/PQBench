import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi import HTTPException
import sessions
from sniffer import (
        app, name_dir, _and_ports, _build_domain_bpf, _resolve_domain_ips,
        _split_streams_tshark, _capture_job, _build_bpf_filter, _start_single_target
    )
import sniffer  # Import the full module to patch socket

# Use FastAPI's TestClient for testing the routes
from fastapi.testclient import TestClient


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
        sniffer._sniffer_handles = {}

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

    # --- New tests for _build_bpf_filter ---
    def test_build_bpf_filter_mode_none(self):
        target = types.SimpleNamespace(filter_mode="none", ports=None)
        bpf = _build_bpf_filter(target, "1.2.3.4")
        self.assertEqual(bpf, "(host 1.2.3.4) and (ip or ip6)")

    def test_build_bpf_filter_mode_custom(self):
        target = types.SimpleNamespace(filter_mode="custom", custom_bpf="tcp or udp", ports="80")
        bpf = _build_bpf_filter(target, "1.2.3.4")
        self.assertEqual(bpf, "((host 1.2.3.4) and (tcp or udp)) and (tcp port 80)")

    def test_build_bpf_filter_mode_invalid(self):
        target = types.SimpleNamespace(filter_mode="invalid_mode")
        with self.assertRaises(HTTPException) as cm:
            _build_bpf_filter(target, "1.2.3.4")
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("unknown filter_mode", cm.exception.detail)

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
            mock_which.assert_called_with("tshark")
            mock_check_output.assert_not_called()

    @patch('subprocess.run')
    @patch('subprocess.check_output')
    @patch('sniffer.which', return_value='/usr/bin/tshark')
    def test_split_streams_tshark_happy(self, mock_which, mock_check_output, mock_run):

        def fake_check_output(cmd, text=True):
            cmd_str = " ".join(cmd)
            if "tls.handshake.type==1" in cmd_str:
                return "1\n\n2\n1\n"
            if "tcp.stream==1" in cmd_str and "-e" in cmd_str and "frame.number" in cmd_str:
                return "frame\n" * 40
            if "tcp.stream==2" in cmd_str and "-e" in cmd_str and "frame.number" in cmd_str:
                return "frame\n" * 10
            return ""

        mock_check_output.side_effect = fake_check_output
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
            _split_streams_tshark(str(input_pcap), str(outdir), "121", "timestamp", min_packets=30)
            mock_which.assert_called_with("tshark")
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

    # --- New tests for _start_single_target ---
    @patch('sniffer._register_and_start_session')
    @patch('sniffer._build_bpf_filter', return_value="fake-bpf")
    @patch('sniffer._create_output_directories', return_value=("/tmp/child", "/tmp/child/raw.pcap"))
    @patch('sniffer._validate_interface')
    @patch('sniffer._generate_session_code', return_value="121")
    def test_start_single_target_success(self, mock_gen_code, mock_val_iface, mock_create_dirs, mock_build_bpf,
                                         mock_reg_start):
        target = types.SimpleNamespace(
            container_ip="1.2.3.4", os="linux", browser="chrome", algo=1,
            iface="eth0", duration_sec=10, filter_mode="none",
            session_count=1
        )
        seen = set()
        timestamp = "fake-time"

        result = _start_single_target(target, timestamp, seen)

        self.assertIsNotNone(result)
        self.assertEqual(seen, {("1.2.3.4", "121")})
        self.assertEqual(result['code'], "121")
        self.assertEqual(result['bpf'], "fake-bpf")
        mock_reg_start.assert_called_once()
        # Check that the ChildSession object passed to register has the right duration
        args, _ = mock_reg_start.call_args
        self.assertEqual(args[2], 10)  # duration_sec

    @patch('sniffer._register_and_start_session')
    def test_start_single_target_skips_duplicate(self, mock_reg_start):
        target = types.SimpleNamespace(container_ip="1.2.3.4", os="linux", browser="chrome", algo=1)
        seen = {("1.2.3.4", "121")}  # Already seen
        timestamp = "fake-time"

        with patch('sniffer._generate_session_code', return_value="121"):
            result = _start_single_target(target, timestamp, seen)

        self.assertIsNone(result)
        mock_reg_start.assert_not_called()

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
        response = self.client.post("/done", json={"foo": "bar"})
        self.assertEqual(response.status_code, 400)

    @patch('sniffer._resolve_ip_from_url', side_effect=ValueError("Resolution failed"))
    def test_done_route_url_resolution_fails(self, mock_resolve):
        response = self.client.post("/done", json={"url": "http://invalid-url"})
        self.assertEqual(response.status_code, 500)
        self.assertIn("internal error", response.json()['detail'])

    @patch('sniffer.socket.gethostbyname', return_value="1.2.3.4")
    def test_done_route_by_url(self, mock_gethostbyname):
        response = self.client.post("/done", json={"url": "http://example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["container_ip"], "1.2.3.4")
        self.assertEqual(response.json()["stopped_session_ids"], [])

    def test_done_route_stops_session(self):
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

    @patch('sniffer._resolve_domain_ips', return_value=(["1.1.1.1"], []))
    @patch('sniffer.get_if_list', return_value=["eth0"])
    def test_start_batch_domain_filter_default_domain(self, mock_get_if_list, mock_resolve_domain_ips):
        payload = {
            "targets": [{
                "os": "linux", "browser": "chrome", "algo": 1,
                "container_ip": "1.2.3.4", "iface": "eth0",
                "filter_mode": "domain",
                "duration_sec": 10
            }]
        }
        response = self.client.post("/start", json=payload)
        self.assertEqual(response.status_code, 200)
        # Verify that _resolve_domain_ips was called with the default domain
        mock_resolve_domain_ips.assert_called_once_with("pq.cloudflareresearch.com")

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
        mock_armed_event = MagicMock()
        mock_armed_event.wait.return_value = True
        mock_event.return_value = mock_armed_event
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

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["started"])
        self.assertEqual(len(data["children"]), 1)
        child = data["children"][0]
        self.assertEqual(child["container_ip"], "1.2.3.4")
        self.assertEqual(child["code"], "121")
        # Note: The bpf assertion is removed as we are not mocking _build_bpf_filter globally anymore
        self.assertEqual(len(sniffer._sessions), 1)
        self.assertEqual(len(sniffer._stop_events), 1)
        mock_thread.assert_called_once()
        mock_thread_instance.start.assert_called_once()
        mock_armed_event.wait.assert_called_once()


# New Test Class for the capture job
class TestCaptureJob(unittest.TestCase):

    def setUp(self):
        # Reset state before each test
        sniffer._sessions = {}
        sniffer._stop_events = {}
        sniffer._sniffer_handles = {}

    @patch('sniffer._split_streams_tshark')
    @patch('sniffer.wrpcap')
    @patch('sniffer.AsyncSniffer')
    @patch('time.sleep')
    @patch('time.time')
    def test_capture_job_stops_by_duration(self, mock_time, mock_sleep, mock_sniffer, mock_wrpcap, mock_split):
        # Simulate time passing to trigger duration timeout
        mock_time.side_effect = [1000.0, 1000.1, 1030.0, 1061.0]  # start, first check, second check, final check

        # Mock sniffer
        mock_sniffer_instance = MagicMock()
        mock_sniffer_instance.stop.return_value = [1, 2, 3]  # 3 packets
        mock_sniffer.return_value = mock_sniffer_instance

        # Setup session
        session_id = "test_duration"
        cs = sessions.ChildSession(session_id=session_id, container_ip="1.2.3.4", code="121",
            iface="eth0", bpf="fake-bpf", outfile="/tmp/out.pcap", started_at=1000.0, duration_sec=60,
            packets=0, done=False, error=None, child_dir="/tmp") # Added started_at and duration_sec

        sniffer._sessions[session_id] = cs
        sniffer._stop_events[session_id] = MagicMock(is_set=lambda: False)  # Event is never set

        _capture_job(session_id, duration=60, timestamp="ts", armed_evt=None)

        mock_sniffer_instance.start.assert_called_once()
        # Loop runs, sleeps, then duration is met
        self.assertGreaterEqual(mock_sleep.call_count, 1)
        mock_sniffer_instance.stop.assert_called_once()
        mock_wrpcap.assert_called_with("/tmp/out.pcap", [1, 2, 3])
        mock_split.assert_called_once()
        self.assertTrue(cs.done)
        self.assertEqual(cs.packets, 3)

    @patch('sniffer._split_streams_tshark')
    @patch('sniffer.wrpcap')
    @patch('sniffer.AsyncSniffer')
    @patch('time.sleep')
    @patch('time.time', return_value=1000.0)
    def test_capture_job_stops_by_event(self, mock_time, mock_sleep, mock_sniffer, mock_wrpcap, mock_split):
        # Mock sniffer
        mock_sniffer_instance = MagicMock()
        mock_sniffer_instance.stop.return_value = []  # 0 packets
        mock_sniffer.return_value = mock_sniffer_instance

        # Setup session and stop event
        session_id = "test_event"
        cs = sessions.ChildSession(session_id=session_id, container_ip="1.2.3.4", code="121", iface="eth0",
                                   bpf="fake-bpf", outfile="/tmp/out.pcap", packets=0, done=False, error=None,
                                   child_dir="/tmp", started_at=1000.0, duration_sec=300)
        sniffer._sessions[session_id] = cs
        # Simulate event being set on the first check in the loop
        stop_event = MagicMock()
        stop_event.is_set.return_value = True
        sniffer._stop_events[session_id] = stop_event

        _capture_job(session_id, duration=300, timestamp="ts", armed_evt=None)

        mock_sniffer_instance.start.assert_called_once()
        mock_sleep.assert_not_called()  # Loop should exit immediately
        mock_sniffer_instance.stop.assert_called_once()
        mock_wrpcap.assert_called_with("/tmp/out.pcap", [])
        mock_split.assert_not_called()  # No packets, so no split
        self.assertTrue(cs.done)
        self.assertEqual(cs.packets, 0)

    @patch('sniffer.AsyncSniffer', side_effect=RuntimeError("Scapy failed"))
    def test_capture_job_handles_exception(self, mock_sniffer):
        session_id = "test_exc"
        cs = sessions.ChildSession(session_id=session_id, container_ip="1.2.3.4", code="121", iface="eth0",
                                   bpf="fake-bpf", outfile="/tmp/out.pcap", packets=0, done=False, error=None,
                                   child_dir="/tmp", started_at=1000.0, duration_sec=300)
        sniffer._sessions[session_id] = cs
        sniffer._stop_events[session_id] = MagicMock()

        _capture_job(session_id, duration=30, timestamp="ts", armed_evt=None)

        self.assertTrue(cs.done)
        self.assertIn("Scapy failed", cs.error)
        self.assertEqual(len(sniffer._sniffer_handles), 0)  # Ensure cleanup happens


if __name__ == '__main__':
    unittest.main()
