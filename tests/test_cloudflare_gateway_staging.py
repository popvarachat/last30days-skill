import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CF = ROOT / "integrations" / "cloudflare"
WORKER = CF / "src" / "index.js"
EXECUTOR = CF / "local_executor.py"
SCHEMA = CF / "schema.sql"
WRANGLER = CF / "wrangler.toml.example"


def test_gateway_is_staging_only_and_uses_split_tokens():
    text = WORKER.read_text(encoding="utf-8")
    assert '!== "staging"' in text
    assert "CLIENT_API_TOKEN" in text
    assert "EXECUTOR_API_TOKEN" in text
    assert "/v1/research" in text
    assert "/v1/executor/claim" in text
    assert "/result" in text


def test_gateway_uses_d1_prepared_statements_and_leases():
    text = WORKER.read_text(encoding="utf-8")
    assert "env.DB.prepare(" in text
    assert ".bind(" in text
    assert "lease_expires_at" in text
    assert "status='queued'" in text
    assert "status='running'" in text


def test_schema_has_bounded_job_states_and_claim_index():
    text = SCHEMA.read_text(encoding="utf-8")
    assert "queued','running','completed','failed" in text
    assert "idx_research_jobs_claim" in text
    assert "request_json TEXT NOT NULL" in text


def test_wrangler_example_contains_no_secret_values():
    text = WRANGLER.read_text(encoding="utf-8")
    assert 'ENVIRONMENT = "staging"' in text
    assert "REPLACE_WITH_STAGING_D1_ID" in text
    lowered = text.lower()
    assert "ghp_" not in lowered
    assert "sk-" not in lowered
    assert "client_api_token =" not in lowered
    assert "executor_api_token =" not in lowered


def _load_executor():
    spec = importlib.util.spec_from_file_location("research_local_executor", EXECUTOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_executor_claims_then_posts_result_without_inbound_server(monkeypatch):
    module = _load_executor()
    calls = []

    def fake_request(url, token, method="GET", payload=None, executor_id="rdc-local"):
        calls.append((url, method, payload))
        if url.endswith("/v1/executor/claim"):
            return {"ok": True, "job": {"job_id": "job-1", "request": {"topic": "GitHub"}}}
        return {"ok": True}

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "_run_bridge", lambda payload: {"ok": True, "result": {"schema_version": "1.5"}})
    assert module.run_once("https://gateway.example", "dummy", "rdc-test") is True
    assert calls[0][1] == "POST"
    assert calls[1][0].endswith("/v1/executor/jobs/job-1/result")
    assert not hasattr(module, "HTTPServer")


def test_executor_forces_local_tool_path_and_disables_browser_reads_by_default():
    text = EXECUTOR.read_text(encoding="utf-8")
    assert 'Path.home() / ".local" / "bin"' in text
    assert 'child_env.setdefault("FROM_BROWSER", "off")' in text
    assert "shell=True" not in text
