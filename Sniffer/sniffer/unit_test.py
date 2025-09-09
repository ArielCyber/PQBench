import subprocess
import types
import pytest
import sniffer


# monkeypatch is a pytest fixture that makes it easy to temporarily change (or “patch”) code during tests,
# without permanently modifying your source files.

# ---------- name_dir ----------
def test_name_dir_valid():
    assert sniffer.name_dir("linux", "chrome", 2) == "122"
    assert sniffer.name_dir("windows", "firefox", 1) == "211"
    assert sniffer.name_dir("macos", "chrome", 0) == "320"


def test_name_dir_invalid_os():
    with pytest.raises(ValueError):
        sniffer.name_dir("solaris", "chrome", 1)


def test_name_dir_invalid_browser():
    with pytest.raises(ValueError):
        sniffer.name_dir("linux", "opera", 1)


# ---------- _and_ports ----------
def test_and_ports_none():
    assert sniffer._and_ports("(ip or ip6)", None) == "(ip or ip6)"


def test_and_ports_single():
    out = sniffer._and_ports("(ip)", "443")
    assert out == "((ip)) and (tcp port 443)"


def test_and_ports_multi():
    out = sniffer._and_ports("(ip)", "443,80,  8443")
    # order must be preserved for readability
    assert out == "((ip)) and ((tcp port 443) or (tcp port 80) or (tcp port 8443))"


def test_and_ports_ignores_bad_tokens():
    out = sniffer._and_ports("(ip)", "443,foo,bar, 80")
    assert out == "((ip)) and ((tcp port 443) or (tcp port 80))"


# ---------- _build_domain_bpf ----------
def test_build_domain_bpf_with_ips():
    bpf = sniffer._build_domain_bpf(
        "10.0.0.5",
        ["1.1.1.1", "9.9.9.9"],
        ["2606:4700:4700::1111"]
    )
    # spot-check: must scope to host + include ip/ip6 clauses
    assert bpf.startswith("(host 10.0.0.5) and (")
    assert "ip and ((dst host 1.1.1.1 or src host 1.1.1.1) or (dst host 9.9.9.9 or src host 9.9.9.9))" in bpf
    assert "ip6 and ((dst host 2606:4700:4700::1111 or src host 2606:4700:4700::1111))" in bpf


def test_build_domain_bpf_fallback_when_empty():
    bpf = sniffer._build_domain_bpf("10.0.0.5", [], [])
    assert bpf == "(host 10.0.0.5) and (ip or ip6)"


# ---------- _resolve_domain_ips ----------
def test_resolve_domain_ips_success(monkeypatch):
    def fake_getaddrinfo(host, *_args, **_kwargs):
        # Simulate two v4 and one v6 result
        return [
            (sniffer.socket.AF_INET, None, None, None, ("1.2.3.4", 0)),
            (sniffer.socket.AF_INET6, None, None, None, ("2001:db8::1", 0, 0, 0)),
            (sniffer.socket.AF_INET, None, None, None, ("5.6.7.8", 0)),
        ]

    monkeypatch.setattr(sniffer.socket, "getaddrinfo", fake_getaddrinfo)
    v4, v6 = sniffer._resolve_domain_ips("example.com")
    assert v4 == ["1.2.3.4", "5.6.7.8"]
    assert v6 == ["2001:db8::1"]


def test_resolve_domain_ips_failure(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("dns failure")

    monkeypatch.setattr(sniffer.socket, "getaddrinfo", boom)
    v4, v6 = sniffer._resolve_domain_ips("example.com")
    assert v4 == []
    assert v6 == []


# ---------- _split_streams_tshark ----------
def test_split_streams_tshark_no_tshark(monkeypatch, tmp_path):
    # Simulate no tshark installed by making check_output raise FileNotFoundError
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    # Also ensure run is never called
    called = {"run": False}

    def fake_run(*a, **k):
        called["run"] = True
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    input_pcap = tmp_path / "in.pcap"
    input_pcap.write_bytes(b"")  # empty file is fine for this test
    sniffer._split_streams_tshark(str(input_pcap), str(tmp_path / "streams"))
    assert called["run"] is False  # we skip extraction when tshark is missing


def test_split_streams_tshark_happy(monkeypatch, tmp_path):
    # Return some stream IDs, including duplicates and blanks
    def fake_check_output(cmd, text=True):
        assert "-e" in cmd and "tcp.stream" in cmd
        return "1\n\n2\n1\n"

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)

    # Collect the attempted runs for extraction
    calls = []

    def fake_run(cmd, check=False):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    input_pcap = tmp_path / "in.pcap"
    input_pcap.write_bytes(b"\xd4\xc3\xb2\xa1")  # pcap magic header (not required, but nice)
    outdir = tmp_path / "streams"
    sniffer._split_streams_tshark(str(input_pcap), str(outdir))
    # Should extract unique streams 1 and 2
    assert any("tcp.stream==1" in " ".join(c) for c in calls)
    assert any("tcp.stream==2" in " ".join(c) for c in calls)
