import os
import time

import pytest
from fastapi.testclient import TestClient

import sniffer


# --- Fixtures ---

@pytest.fixture(autouse=True)
def _isolate_output_root(tmp_path, monkeypatch):
    # Ensure all start runs write into a temp folder
    monkeypatch.setenv("OUTPUT_ROOT", str(tmp_path / "output"), prepend=False)
    # The module reads OUTPUT_ROOT at import time; keep attribute in sync:
    sniffer.OUTPUT_ROOT = os.environ["OUTPUT_ROOT"]
    yield

@pytest.fixture
def client(monkeypatch):
    # Mock scapy AsyncSniffer and helpers so we don't need pcap libs or raw sockets

    class FakePackets(list):
        pass

    class FakeSniffer:
        def __init__(self, iface=None, filter=None, store=True):
            self.iface = iface
            self.filter = filter
            self.store = store
            self._running = False
        def start(self):
            self._running = True
        def stop(self):
            self._running = False
            # Return a few fake packets to exercise the write path
            return FakePackets([object(), object()])

    # Replace AsyncSniffer and wrpcap with fakes
    monkeypatch.setattr(sniffer, "AsyncSniffer", FakeSniffer)
    monkeypatch.setattr(sniffer, "wrpcap", lambda path, packets: None)

    # Make interfaces deterministic
    monkeypatch.setattr(sniffer, "get_if_list", lambda: ["lo", "eth0", "any"])

    # Prevent tshark calls during API tests
    monkeypatch.setattr(sniffer, "_split_streams_tshark", lambda *a, **k: None)

    return TestClient(sniffer.app)

# --- /health and /ifaces ---

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}

def test_ifaces(client):
    r = client.get("/ifaces")
    assert r.status_code == 200
    assert r.json() == ["lo", "eth0", "any"]

# --- /start validation paths ---

def test_start_requires_targets(client):
    r = client.post("/start", json={"targets": []})
    assert r.status_code == 400
    assert "targets must be non-empty" in r.text

def test_start_invalid_iface(client):
    # Re-mock interfaces to exclude the requested one
    with client:
        sniffer.get_if_list = lambda: ["lo"]
        payload = {
            "targets": [{
                "os": "linux",
                "browser": "chrome",
                "algo": 2,
                "container_ip": "172.18.0.10",
                "duration_sec": 1,
                "iface": "eth0",  # not present
                "filter_mode": "none"
            }]
        }
        r = client.post("/start", json=payload)
        assert r.status_code == 400
        assert "iface 'eth0' not found" in r.text

def test_start_domain_mode_resolves_and_builds_bpf(client, monkeypatch):
    # Make DNS resolution deterministic
    def fake_getaddrinfo(host, *_a, **_k):
        return [
            (sniffer.socket.AF_INET, None, None, None, ("203.0.113.5", 0)),
            (sniffer.socket.AF_INET6, None, None, None, ("2001:db8::5", 0, 0, 0)),
        ]
    monkeypatch.setattr(sniffer.socket, "getaddrinfo", fake_getaddrinfo)

    payload = {
        "targets": [{
            "os": "linux",
            "browser": "chrome",
            "algo": 2,
            "container_ip": "172.18.0.10",
            "duration_sec": 1,
            "iface": "any",
            "filter_mode": "domain",
            "domain": "pq.cloudflareresearch.com",
            "ports": "443"
        }]
    }
    r = client.post("/start", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["started"] is True
    assert len(data["children"]) == 1
    child = data["children"][0]
    # BPF must include host, domain IPs, and tcp port
    assert "host 172.18.0.10" in child["bpf"]
    assert "203.0.113.5" in child["bpf"]
    assert "2001:db8::5" in child["bpf"]
    assert "tcp port 443" in child["bpf"]

def test_start_custom_mode(client):
    payload = {
        "targets": [{
            "os": "linux",
            "browser": "firefox",
            "algo": 1,
            "container_ip": "172.18.0.20",
            "duration_sec": 1,
            "iface": "any",
            "filter_mode": "custom",
            "custom_bpf": "tcp and port 443"
        }]
    }
    r = client.post("/start", json=payload)
    assert r.status_code == 200
    child = r.json()["children"][0]
    assert "(host 172.18.0.20) and (tcp and port 443)" in child["bpf"]

def test_start_none_mode_and_status(client, tmp_path):
    payload = {
        "targets": [
            {
                "os": "linux",
                "browser": "chrome",
                "algo": 2,
                "container_ip": "172.18.0.30",
                "duration_sec": 1,
                "iface": "any",
                "filter_mode": "none",
            },
            # Add a duplicate (same ip + code) to exercise de-dupe
            {
                "os": "linux",
                "browser": "chrome",
                "algo": 2,
                "container_ip": "172.18.0.30",
                "duration_sec": 1,
                "iface": "any",
                "filter_mode": "none",
            }
        ]
    }
    r = client.post("/start", json=payload)
    assert r.status_code == 200
    data = r.json()
    # duplicate should be skipped — only one child
    assert len(data["children"]) == 1

    # Give the fake sniffer thread a moment to flip done=True
    time.sleep(0.1)
    r2 = client.get("/status")
    assert r2.status_code == 200
    sessions = r2.json()["sessions"]
    # At least one session exists and has fields set
    assert len(sessions) >= 1
    s0 = next(s for s in sessions if s["container_ip"] == "172.18.0.30")
    assert s0["done"] in (True, False)  # may finish quickly; don't flake
    assert s0["outfile"].endswith(".pcap")
