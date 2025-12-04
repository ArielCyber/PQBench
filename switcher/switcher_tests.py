import json

import pytest

import switcher


# -----------------------------
# Fixtures & helper structures
# -----------------------------


@pytest.fixture
def base_containers_and_algos(monkeypatch):
    """
    Set up Containers and ALGO_NAME_TO_CODE so parse_jobs_from_payload works.
    """
    # algo name -> code
    monkeypatch.setattr(
        switcher,
        "ALGO_NAME_TO_CODE",
        {
            "kyber": 1,
            "mlkem": 2,
            "non-pqc": 0,
        },
    )

    # container key -> base URL
    monkeypatch.setattr(
        switcher,
        "Containers",
        {
            "windows_kyber": "http://windows-kyber:5000/",
            "windows_mlkem": "http://windows-mlkem:5000/",
            "linux_kyber": "http://linux-kyber:5000/",
        },
    )


# =========================
# Tests: parse_jobs_from_payload
# =========================


def test_parse_jobs_from_payload_single_valid_job(base_containers_and_algos):
    payload = {
        "os": "windows",
        "browser": "chrome",
        "algorithm": "kyber",
        "sessions": 5,
    }

    raw_jobs, jobs, errors = switcher.parse_jobs_from_payload(payload)

    assert len(raw_jobs) == 1
    assert errors == []
    assert len(jobs) == 1

    job = jobs[0]
    assert job["idx"] == 0
    assert job["opsys"] == "windows"
    assert job["browser"] == "chrome"
    assert job["algo_name"] == "kyber"
    assert job["algo_code"] == 1
    assert job["sessions"] == 5
    # choose_container("windows", "kyber") -> "windows_kyber"
    assert job["target_key"] == "windows_kyber"
    # Containers["windows_kyber"] rstrip("/") -> "http://windows-kyber:5000"
    assert job["target_base"] == "http://windows-kyber:5000"


def test_parse_jobs_from_payload_invalid_os(base_containers_and_algos):
    payload = {
        "os": "solaris",
        "browser": "chrome",
        "algorithm": "kyber",
        "sessions": 5,
    }

    raw_jobs, jobs, errors = switcher.parse_jobs_from_payload(payload)

    assert len(raw_jobs) == 1
    assert jobs == []
    assert len(errors) == 1
    assert errors[0]["index"] == 0
    # Full message: "Invalid operating system. Must be 'linux', 'windows', or 'macos'."
    assert "Invalid operating system" in errors[0]["error"]


def test_parse_jobs_from_payload_invalid_sessions_non_integer(base_containers_and_algos):
    payload = {
        "os": "windows",
        "browser": "chrome",
        "algorithm": "kyber",
        "sessions": "abc",  # invalid
    }

    raw_jobs, jobs, errors = switcher.parse_jobs_from_payload(payload)

    assert len(raw_jobs) == 1
    assert jobs == []
    assert len(errors) == 1
    assert errors[0]["index"] == 0
    assert "sessions must be an integer > 0" in errors[0]["error"]


def test_parse_jobs_from_payload_invalid_algorithm(base_containers_and_algos):
    payload = {
        "os": "windows",
        "browser": "chrome",
        "algorithm": "rsa",
        "sessions": 5,
    }

    raw_jobs, jobs, errors = switcher.parse_jobs_from_payload(payload)

    assert len(raw_jobs) == 1
    assert jobs == []
    assert len(errors) == 1
    assert errors[0]["index"] == 0
    assert "Invalid algorithm" in errors[0]["error"]


# =========================
# Tests: run_single_job
# =========================


class DummySemaphore:
    """No-op semaphore used for tests to satisfy 'with'."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def basic_job_definition():
    return {
        "idx": 0,
        "opsys": "windows",
        "browser": "chrome",
        "algo_name": "non-pqc",
        "algo_code": 0,
        "sessions": 3,
        "target_key": "windows_non-pqc",         # only used as a key into _backend_slots
        "target_base": "http://windows-nonpqc",  # used for resolve_service_ip
    }


def test_run_single_job_sender_done_early_stop(monkeypatch, basic_job_definition):
    """
    Sender reports status=done -> we should skip polling and stop sniffer immediately.
    """

    # Make sniffer wait plan deterministic
    monkeypatch.setattr(
        switcher,
        "compute_sniffer_wait_plan",
        lambda session_count: (1.0, 60.0),
    )

    # Configure to stop on sender 'done'
    monkeypatch.setattr(
        switcher,
        "get_sender_behavior_config",
        lambda: (True, 0.0),  # stop_on_sender_done=True, grace=0
    )

    # Backend semaphore & service ip resolution
    monkeypatch.setattr(
        switcher,
        "_backend_slots",
        {"windows_non-pqc": DummySemaphore()},
    )
    monkeypatch.setattr(
        switcher,
        "resolve_service_ip",
        lambda base_url: "10.0.0.5",
    )

    # Sniffer start stub
    def fake_start_sniffer(job, backend_ip, max_wait):
        assert backend_ip == "10.0.0.5"
        return {"status": 200, "response": {"ok": True}}, ["sess-1", "sess-2"]

    monkeypatch.setattr(switcher, "start_sniffer", fake_start_sniffer)

    # Sender execute stub: explicitly "done"
    def fake_execute_sender(job):
        return {"status": 200, "response": {"status": "done"}}

    monkeypatch.setattr(switcher, "execute_sender", fake_execute_sender)

    # stop_sniffer stub
    def fake_stop_sniffer(job, backend_ip, session_ids):
        assert backend_ip == "10.0.0.5"
        assert session_ids == ["sess-1", "sess-2"]
        return {"status": 200, "response": {"stopped": True}}

    monkeypatch.setattr(switcher, "stop_sniffer", fake_stop_sniffer)

    # poll_sniffer_until_done should NOT be called in early-stop path
    def fail_poll(*args, **kwargs):
        raise AssertionError("poll_sniffer_until_done should not be called in early-stop path")

    monkeypatch.setattr(switcher, "poll_sniffer_until_done", fail_poll)

    result = switcher.run_single_job(basic_job_definition)

    assert result["routed_to"] == "windows_non-pqc"
    assert result["backend"]["execute"]["response"]["status"] == "done"

    wait_info = result["sniffer"]["wait"]
    assert wait_info["polled"] is False
    assert wait_info["finished"] is True
    assert wait_info["reason"] == "sender_done"
    assert wait_info["samples"] == []


def test_run_single_job_polling_path(monkeypatch, basic_job_definition):
    """
    Sender does NOT say 'done' -> we should poll sniffer /status and then call /done.
    """

    # Deterministic wait plan
    monkeypatch.setattr(
        switcher,
        "compute_sniffer_wait_plan",
        lambda session_count: (2.0, 30.0),
    )

    # Still configured to stop on sender 'done', but sender won't say done.
    monkeypatch.setattr(
        switcher,
        "get_sender_behavior_config",
        lambda: (True, 0.0),
    )

    monkeypatch.setattr(
        switcher,
        "_backend_slots",
        {"windows_non-pqc": DummySemaphore()},
    )
    monkeypatch.setattr(
        switcher,
        "resolve_service_ip",
        lambda base_url: "10.0.0.6",
    )

    def fake_start_sniffer(job, backend_ip, max_wait):
        assert backend_ip == "10.0.0.6"
        return {"status": 200, "response": {"ok": True}}, ["sess-42"]

    monkeypatch.setattr(switcher, "start_sniffer", fake_start_sniffer)

    # Sender does NOT say "done" (no status key)
    def fake_execute_sender(job):
        return {"status": 200, "response": {"detail": "finished but no done flag"}}

    monkeypatch.setattr(switcher, "execute_sender", fake_execute_sender)

    # Polling result stub
    def fake_poll_sniffer_until_done(job, session_ids, poll_interval, max_wait):
        assert session_ids == ["sess-42"]
        return True, [{"sample": 1}], 12.5  # finished=True, one sample, elapsed=12.5

    monkeypatch.setattr(switcher, "poll_sniffer_until_done", fake_poll_sniffer_until_done)

    def fake_stop_sniffer(job, backend_ip, session_ids):
        assert backend_ip == "10.0.0.6"
        assert session_ids == ["sess-42"]
        return {"status": 200, "response": {"stopped": True}}

    monkeypatch.setattr(switcher, "stop_sniffer", fake_stop_sniffer)

    result = switcher.run_single_job(basic_job_definition)

    assert result["routed_to"] == "windows_non-pqc"
    assert result["backend"]["execute"]["response"]["detail"].startswith("finished")

    wait_info = result["sniffer"]["wait"]
    assert wait_info["polled"] is True
    assert wait_info["finished"] is True
    assert wait_info["samples"] == [{"sample": 1}]
    assert wait_info["elapsed_sec"] == 12.5


# =========================
# Tests: /config handler (Flask)
# =========================


def test_config_handler_success(monkeypatch):
    """
    Full /config handler test using Flask test client, with monkeypatched
    parsing + job runner. We let the real ThreadPoolExecutor run, but it
    just calls our fake run_single_job.
    """
    app = switcher.app

    # Replace parse_jobs_from_payload so we don't depend on real maps for this test
    def fake_parse_jobs_from_payload(payload):
        # 1 raw job, 1 valid job, no errors
        fake_job = {
            "idx": 0,
            "opsys": "windows",
            "browser": "chrome",
            "algo_name": "non-pqc",
            "algo_code": 0,
            "sessions": 3,
            "target_key": "windows_non-pqc",
            "target_base": "http://windows-nonpqc",
        }
        return [payload], [fake_job], []

    monkeypatch.setattr(
        switcher,
        "parse_jobs_from_payload",
        fake_parse_jobs_from_payload,
    )

    # run_single_job stub – this is what the executor will actually run
    def fake_run_single_job(job_def):
        return {
            "routed_to": job_def["target_key"],
            "backend": {"execute": {"status": 200, "response": {"ok": True}}},
            "sniffer": {"start": {}, "wait": {}, "done": {}},
        }

    monkeypatch.setattr(switcher, "run_single_job", fake_run_single_job)

    with app.test_client() as client:
        response = client.post("/config", json={"os": "windows"})
        assert response.status_code == 207

        body = json.loads(response.data.decode("utf-8"))
        assert "backends" in body
        assert len(body["backends"]) == 1

        backend_result = body["backends"][0]
        assert backend_result["routed_to"] == "windows_non-pqc"
        assert backend_result["backend"]["execute"]["status"] == 200
        assert backend_result["backend"]["execute"]["response"]["ok"] is True


def test_config_handler_no_valid_jobs(monkeypatch):
    """
    When parse_jobs_from_payload returns no valid jobs, /config should return HTTP 400.
    """
    app = switcher.app

    def fake_parse_jobs_from_payload(payload):
        # No valid jobs, one error
        return [payload], [], [{"index": 0, "error": "Bad job"}]

    monkeypatch.setattr(
        switcher,
        "parse_jobs_from_payload",
        fake_parse_jobs_from_payload,
    )

    with app.test_client() as client:
        response = client.post("/config", json={"os": "windows"})
        assert response.status_code == 400

        body = json.loads(response.data.decode("utf-8"))
        assert body["error"] == "No valid jobs"
        assert len(body["detail"]) == 1
        assert body["detail"][0]["index"] == 0


def test_parse_jobs_from_payload_multiple_jobs_mixed(base_containers_and_algos):
    payload = {
        "jobs": [
            {  # job 0 – valid
                "os": "windows",
                "browser": "chrome",
                "algorithm": "kyber",
                "sessions": 3,
            },
            {  # job 1 – invalid algorithm
                "os": "windows",
                "browser": "chrome",
                "algorithm": "rsa",
                "sessions": 4,
            },
            {  # job 2 – valid
                "os": "linux",
                "browser": "firefox",
                "algorithm": "kyber",
                "sessions": 2,
            },
        ]
    }

    raw_jobs, jobs, errors = switcher.parse_jobs_from_payload(payload)

    # We had 3 raw jobs
    assert len(raw_jobs) == 3

    # Two valid jobs: indices 0 and 2
    assert len(jobs) == 2
    job_indices = sorted(job["idx"] for job in jobs)
    assert job_indices == [0, 2]

    # One parse error: index 1 should be invalid algorithm
    assert len(errors) == 1
    assert errors[0]["index"] == 1
    assert "Invalid algorithm" in errors[0]["error"]


def test_config_handler_multiple_jobs_with_error(monkeypatch):
    """
    /config with multiple jobs: two valid, one invalid in the middle.
    Verify alignment of results and insertion of parse error.
    """
    app = switcher.app

    # Fake parse_jobs_from_payload to simulate 3 jobs: idx 0 & 2 valid, idx 1 error
    def fake_parse_jobs_from_payload(payload):
        raw_jobs = payload.get("jobs", [])
        valid_jobs = [
            {
                "idx": 0,
                "opsys": "windows",
                "browser": "chrome",
                "algo_name": "non-pqc",
                "algo_code": 0,
                "sessions": 3,
                "target_key": "windows_non-pqc",
                "target_base": "http://windows-nonpqc",
            },
            {
                "idx": 2,
                "opsys": "linux",
                "browser": "firefox",
                "algo_name": "kyber",
                "algo_code": 1,
                "sessions": 2,
                "target_key": "linux_kyber",
                "target_base": "http://linux-kyber",
            },
        ]
        parse_errors = [
            {"index": 1, "error": "Invalid algorithm. Must be 'non-pqc', 'kyber', or 'mlkem'."}
        ]
        return raw_jobs, valid_jobs, parse_errors

    monkeypatch.setattr(
        switcher,
        "parse_jobs_from_payload",
        fake_parse_jobs_from_payload,
    )

    # run_single_job stub
    def fake_run_single_job(job_def):
        return {
            "routed_to": job_def["target_key"],
            "backend": {"execute": {"status": 200, "response": {"job_idx": job_def["idx"]}}},
            "sniffer": {"start": {}, "wait": {}, "done": {}},
        }

    monkeypatch.setattr(switcher, "run_single_job", fake_run_single_job)

    payload = {
        "jobs": [
            {"os": "windows"},          # idx 0 (valid)
            {"os": "windows"},          # idx 1 (error)
            {"os": "linux"},            # idx 2 (valid)
        ]
    }

    with app.test_client() as client:
        response = client.post("/config", json=payload)
        assert response.status_code == 207

        body = json.loads(response.data.decode("utf-8"))
        assert "backends" in body
        backends = body["backends"]

        # We expect 3 entries in backends (0,1,2)
        assert len(backends) == 3

        # Index 0: valid, routed_to windows_non-pqc
        assert backends[0]["routed_to"] == "windows_non-pqc"
        assert backends[0]["backend"]["execute"]["status"] == 200
        assert backends[0]["backend"]["execute"]["response"]["job_idx"] == 0

        # Index 1: parse error
        assert backends[1]["status"] == 400
        assert backends[1]["routed_to"] is None
        assert backends[1]["response"]["index"] == 1
        assert "Invalid algorithm" in backends[1]["response"]["error"]

        # Index 2: valid, routed_to linux_kyber
        assert backends[2]["routed_to"] == "linux_kyber"
        assert backends[2]["backend"]["execute"]["status"] == 200
        assert backends[2]["backend"]["execute"]["response"]["job_idx"] == 2
