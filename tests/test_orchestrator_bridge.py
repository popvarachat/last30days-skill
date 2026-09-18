import json
import subprocess
from pathlib import Path
from unittest import mock

import orchestrator_bridge as bridge


def _payload(**overrides):
    payload = {
        "schema_version": "1.0",
        "request_id": "uaios-research-001",
        "topic": "GitHub AI agents pull request governance",
        "interest_context": ["GitHub Actions", "MCP", "human approval"],
        "sources": ["youtube", "github"],
        "depth": "deep",
        "days": 30,
        "as_of": "2026-09-17",
        "max_results": 25,
    }
    payload.update(overrides)
    return payload


def test_validate_request_normalizes_and_deduplicates_context():
    request = bridge.validate_request(
        _payload(interest_context=[" MCP ", "MCP", "human approval"])
    )
    assert request["interest_context"] == ["MCP", "human approval"]
    assert request["sources"] == ["youtube", "github"]


def test_validate_request_rejects_invalid_boundaries():
    for payload in (
        _payload(sources=["YouTube"]),
        _payload(depth="turbo"),
        _payload(days=0),
        _payload(topic="bad\ncontrol"),
        _payload(unexpected="ignored-no-more"),
    ):
        try:
            bridge.validate_request(payload)
        except bridge.RequestError:
            pass
        else:
            raise AssertionError(f"expected RequestError for {payload!r}")


def test_build_engine_argv_keeps_metacharacters_as_data():
    request = bridge.validate_request(
        _payload(topic='GitHub & whoami ; echo "not a command"')
    )
    argv = bridge.build_engine_argv(request)
    assert request["topic"] in argv
    assert argv[2] == request["topic"]
    assert "--interest-context" in argv
    assert "--search" in argv
    assert argv[argv.index("--search") + 1] == "youtube,github"


def test_run_request_uses_ephemeral_plan_and_returns_agent_contract():
    plan = {
        "intent": "implementation research",
        "freshness_mode": "balanced_recent",
        "cluster_mode": "themes",
        "subqueries": [],
    }
    seen_plan_path = None

    def fake_run(argv, **kwargs):
        nonlocal seen_plan_path
        assert "shell" not in kwargs
        plan_path = Path(argv[argv.index("--plan") + 1])
        seen_plan_path = plan_path
        assert plan_path.exists()
        assert json.loads(plan_path.read_text(encoding="utf-8")) == plan
        output = {"schema_version": "1.5", "results": []}
        return subprocess.CompletedProcess(argv, 0, json.dumps(output), "")

    with mock.patch.object(bridge.subprocess, "run", side_effect=fake_run):
        code, response = bridge.run_request(_payload(plan=plan))

    assert code == 0
    assert response["ok"] is True
    assert response["engine_schema_version"] == "1.5"
    assert seen_plan_path is not None and not seen_plan_path.exists()


def test_invalid_request_does_not_echo_unvalidated_request_id():
    code, response = bridge.run_request(
        _payload(request_id="bad\nheader", depth="turbo")
    )
    assert code == 2
    assert response["ok"] is False
    assert response["request_id"] is None
    assert response["error"]["code"] == "invalid_request"


def test_engine_failure_returns_generic_error_without_child_output():
    child = subprocess.CompletedProcess(
        ["python"], 9, "sensitive stdout", "sensitive stderr"
    )
    with mock.patch.object(bridge.subprocess, "run", return_value=child):
        code, response = bridge.run_request(_payload())
    assert code == 9
    assert response["error"]["code"] == "engine_failed"
    serialized = json.dumps(response)
    assert "sensitive stdout" not in serialized
    assert "sensitive stderr" not in serialized


def test_read_payload_rejects_oversized_file(tmp_path):
    path = tmp_path / "oversized.json"
    path.write_text('{' + '"x":"' + ('a' * 131072) + '"}', encoding="utf-8")
    try:
        bridge._read_payload(str(path))
    except bridge.RequestError as exc:
        assert "128 KiB" in str(exc)
    else:
        raise AssertionError("expected oversized request to be rejected")


def test_write_json_response_uses_utf8_buffer_for_unicode(monkeypatch):
    import io

    class FakeStdout:
        def __init__(self):
            self.buffer = io.BytesIO()

        def write(self, _value):
            raise AssertionError("text encoding path should not be used when buffer exists")

    fake = FakeStdout()
    monkeypatch.setattr(bridge.sys, "stdout", fake)
    bridge._write_json_response({"message": "agent 🤖"})
    assert fake.buffer.getvalue().decode("utf-8") == '{"message": "agent 🤖"}\n'
