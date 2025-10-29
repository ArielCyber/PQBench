import json
import types
import builtins
import time as _time
import os

import pytest

# Adjust the import if your module file isn't named 'switcher.py'
import switcher


# ---------- Test helpers ----------

class FakeResponse:
    def __init__(self, status_code=200, json_body=None, text="OK"):
        self.status_code = status_code
        self._json = json_body
        self.text = text

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._json is None:
            raise ValueError("No JSON")
        return self._json


@pytest.fixture(autouse=True)
def speed_up_sleep(monkeypatch):
    """Make time.sleep no-op so polling loops are instant."""
    monkeypatch.setattr(switcher.time, "sleep", lambda *_args, **_kwargs: None)


@pytest.fixture
def client(monkeypatch):
    """
    Flask test client with environment tuned for quick tests.
    """
    # Keep polling super short and bound total wait so loops end quickly
    env = {
        "SNIFFER_URL": "http://sniffer:8080",
        "SNIFFER_POLL_INTERVAL_SEC": "0.01",
        "SNIFFER_WAIT_PER_SESSION": "0.1",
        "SNIFFER_MAX_WAIT_CAP": "1",
        "SNIFFER_IFACE": "test0",
        "SNIFFER_FILTER_MODE": "domain",
        "SNIFFER_DOMAIN": "example.com",
        "SNIFFER_PORTS": "443",
    }
    with monkeypatch.context() as m:
        for k, v in env.items():
            m.setenv(k, v)
        # Ensure Containers are the expected defaults (if you changed env, update here)
        switcher.Containers.update({
            "linux_kyber":  os.getenv("URL_LINUX_KYBER",  "http://linux-kyber:5000"),
            "linux_mlkem":  os.getenv("URL_LINUX_MLKEM",  "http://linux-mlkem:5000"),
            "windows_kyber":os.getenv("URL_WINDOWS_KYBER","http://windows-kyber:5000"),
            "windows_mlkem":os.getenv("URL_WINDOWS_MLKEM","http://windows-mlkem:5000"),
            "macos_kyber":  os.getenv("URL_MACOS_KYBER",  "http://macos-kyber:5000"),
            "macos_mlkem":  os.getenv("URL_MACOS_MLKEM",  "http://macos-mlkem:5000"),
        })
        yield switcher.app.test_client()


# ---------- Unit tests: pure helpers ----------

@pytest.mark.parametrize(
    "opsys,algo,expected_key",
    [
        ("linux", "kyber",   "linux_kyber"),
        ("LINUX", "KYBER",   "linux_kyber"),
        ("windows", "mlkem", "windows_mlkem"),
        ("macos", "non-pqc", "macos_kyber"),  # current code routes non-pqc -> kyber
    ],
)
def test_choose_container_valid(opsys, algo, expected_key):
    key = switcher.choose_container(opsys, algo)
    assert key == expected_key


def test_choose_container_invalid_combo():
    # algo "invalid" -> algorithm label "invalid" -> key not in Containers
    with pytest.raises(ValueError):
        switcher.choose_container("linux", "invalid-algo")


@pytest.mark.parametrize(
    "os_name,browser,algo,expected",
    [
        ("linux", "firefox", 1, "111"),
        ("windows", "chrome", 2, "232"),
        ("macos", "chrome", 0, "320"),
    ],
)
def test_generate_code_ok(os_name, browser, algo, expected):
    assert switcher.generate_code(os_name, browser, algo) == expected


@pytest.mark.parametrize(
    "os_name,browser,err_contains",
    [
        ("solaris", "chrome", "solaris"),
        ("linux", "safari", "safari"),
    ],
)
def test_generate_code_invalid_inputs(os_name, browser, err_contains):
    with pytest.raises(ValueError) as ei:
        switcher.generate_code(os_name, browser, 1)
    assert err_contains in str(ei.value)


def test_resolve_service_ip(monkeypatch):
    def fake_gethostbyname(host):
        assert host == "linux-kyber"
        return "172.18.0.10"
    monkeypatch.setattr(switcher.socket, "gethostbyname", fake_gethostbyname)
    ip = switcher._resolve_service_ip("http://linux-kyber:5000")
    assert ip == "172.18.0.10"


# ---------- Flask endpoints ----------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.data.decode() == "ok"


# ---------- /config orchestration ----------

def _install_http_fakes_for_happy_path(monkeypatch):
    """
    Install fakes for requests.post/get covering:
      - sniffer /start -> returns children/session_ids
      - sniffer /status -> first: qualified_reached; second: done
      - sniffer /done -> ok
      - backend /execute -> ok
    Also mock DNS resolution.
    """
    # Stateful iterator for /status
    status_bodies = [
        # First poll: reached target (triggers /done call)
        {
            "sessions": [
                {"session_id": "s1", "container_ip": "172.18.0.10", "qualified_reached": True, "done": False}
            ]
        },
        # Second poll: done -> loop exits
        {
            "sessions": [
                {"session_id": "s1", "container_ip": "172.18.0.10", "qualified_reached": True, "done": True}
            ]
        },
    ]
    status_index = {"i": 0}

    def fake_get(url, timeout=5, **_):
        if "/status" in url:
            i = min(status_index["i"], len(status_bodies) - 1)
            body = status_bodies[i]
            status_index["i"] += 1
            return FakeResponse(200, body)
        return FakeResponse(404, {"error": "unknown GET"})

    def fake_post(url, json=None, timeout=30, **_):
        if url.endswith("/start"):
            assert "targets" in (json or {})
            # Return session id for this job
            return FakeResponse(200, {"children": [{"session_id": "s1"}]})
        if url.endswith("/done"):
            # Should be called twice: once on 'reached', once finally
            assert "container_ip" in (json or {})
            return FakeResponse(200, {"ok": True})
        if url.endswith("/execute"):
            # Simulate backend ran OK
            return FakeResponse(200, {"ran": True})
        return FakeResponse(404, {"error": "unknown POST"})

    def fake_dns(host):
        # Resolve any backend host to a stable IP
        return "172.18.0.10"

    monkeypatch.setattr(switcher.requests, "get", fake_get)
    monkeypatch.setattr(switcher.requests, "post", fake_post)
    monkeypatch.setattr(switcher.socket, "gethostbyname", fake_dns)


def test_config_single_job_happy_path(client, monkeypatch):
    _install_http_fakes_for_happy_path(monkeypatch)

    payload = {
        "os": "linux",
        "browser": "chrome",
        "algorithm": "kyber",
        "sessions": 2,
    }
    r = client.post("/config", json=payload)
    assert r.status_code == 207

    body = r.get_json()
    assert "backends" in body and isinstance(body["backends"], list)
    assert body["backends"][0]["routed_to"] == "linux_kyber"

    # Verify presence/shape of sniffer + backend responses
    sn = body["backends"][0]["sniffer"]
    assert sn["start"]["status"] == 200
    assert sn["done"]["status"] == 200
    assert sn["wait"]["finished"] is True

    be = body["backends"][0]["backend"]["execute"]
    assert be["status"] == 200
    assert be["response"].get("ran") is True


def test_config_batch_mixed_valid_and_invalid(client, monkeypatch):
    _install_http_fakes_for_happy_path(monkeypatch)

    # 3 jobs: valid, invalid browser, valid-but-uses-normalization
    payload = {
        "jobs": [
            {"os": "windows", "browser": "firefox", "algorithm": "mlkem", "sessions": 1},   # valid
            {"os": "linux", "browser": "safari",  "algorithm": "kyber", "sessions": 1},     # invalid
            {"operationSystem": "0", "browser": "Chrome", "algo": "1", "count": "2"},        # normalized
        ]
    }
    r = client.post("/config", json=payload)
    assert r.status_code == 207
    body = r.get_json()
    backends = body["backends"]
    assert len(backends) == 3

    # index 0: valid windows/mlkem -> routed_to windows_mlkem
    assert backends[0]["routed_to"] == "windows_mlkem"
    assert backends[0]["backend"]["execute"]["status"] == 200

    # index 1: invalid browser -> error block with 400 status included
    assert backends[1]["status"] == 400
    assert backends[1]["response"]["error"] == "Invalid web browser"

    # index 2: normalization
    # OS_MAP "0"->"linux"; ALGO_MAP "1"->"kyber"; Chrome->chrome; sessions "2"->2
    assert backends[2]["routed_to"] == "linux_kyber"
    assert backends[2]["backend"]["execute"]["status"] == 200


def test_config_rejects_all_invalid_jobs(client):
    # sessions missing/invalid -> no valid jobs
    payload = {"os": "linux", "browser": "chrome", "algorithm": "kyber", "sessions": "NaN"}
    r = client.post("/config", json=payload)
    assert r.status_code == 400
    data = r.get_json()
    assert data["error"] == "No valid jobs"
    assert isinstance(data["detail"], list) and data["detail"][0]["error"].startswith("Bad job")


def test_config_invalid_fields_messages(client):
    # explicit invalid values for each field
    r = client.post("/config", json={"os": "amiga", "browser": "chrome", "algorithm": "kyber", "sessions": 1})
    assert r.status_code == 400 or r.status_code == 207  # single invalid job path returns 400; batch wraps in 207
    if r.status_code == 207:
        body = r.get_json()
        assert body["backends"][0]["status"] == 400
        assert body["backends"][0]["response"]["error"] == "Invalid operating system"
    else:
        body = r.get_json()
        assert body["error"] == "No valid jobs"
        assert "Invalid operating system" in json.dumps(body["detail"])

    r2 = client.post("/config", json={"os": "linux", "browser": "mosaic", "algorithm": "kyber", "sessions": 1})
    assert r2.status_code in (400, 207)
    r3 = client.post("/config", json={"os": "linux", "browser": "chrome", "algorithm": "rsa", "sessions": 1})
    assert r3.status_code in (400, 207)
    r4 = client.post("/config", json={"os": "linux", "browser": "chrome", "algorithm": "kyber", "sessions": 0})
    assert r4.status_code in (400, 207)


def test_config_handles_sniffer_or_backend_unreachable(client, monkeypatch):
    """
    Make sniffer /start and backend /execute fail to ensure 502s are captured in the result.
    """
    def fail_post(url, json=None, timeout=30, **_):
        if url.endswith("/start"):
            raise switcher.requests.RequestException("sniffer down")
        if url.endswith("/execute"):
            raise switcher.requests.RequestException("backend down")
        if url.endswith("/done"):
            return FakeResponse(200, {"ok": True})
        return FakeResponse(404)

    def ok_get(url, timeout=5, **_):
        # status unreachable path will be exercised implicitly; but return empty
        return FakeResponse(200, {"sessions": []})

    def fake_dns(_host):
        return "172.18.0.10"

    monkeypatch.setattr(switcher.requests, "post", fail_post)
    monkeypatch.setattr(switcher.requests, "get", ok_get)
    monkeypatch.setattr(switcher.socket, "gethostbyname", fake_dns)

    payload = {"os": "linux", "browser": "chrome", "algorithm": "kyber", "sessions": 1}
    r = client.post("/config", json=payload)
    assert r.status_code == 207
    body = r.get_json()
    be = body["backends"][0]["backend"]["execute"]
    sn = body["backends"][0]["sniffer"]["start"]
    assert sn["status"] == 502 and "sniffer /start unreachable" in json.dumps(sn["response"])
    assert be["status"] == 502 and "backend unreachable" in json.dumps(be["response"])
