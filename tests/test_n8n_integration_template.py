import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SUBMIT = ROOT / "integrations" / "n8n" / "research-intelligence-staging.json"
STATUS = ROOT / "integrations" / "n8n" / "research-intelligence-status-staging.json"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_n8n_submit_workflow_is_inactive_and_async():
    workflow = _load(SUBMIT)
    assert workflow["active"] is False
    names = [node["name"] for node in workflow["nodes"]]
    assert names == ["Webhook", "Normalize Request", "Submit Job", "Respond"]
    submit = next(node for node in workflow["nodes"] if node["name"] == "Submit Job")
    assert submit["parameters"]["method"] == "POST"
    assert "/v1/research" in submit["parameters"]["url"]
    respond = next(node for node in workflow["nodes"] if node["name"] == "Respond")
    assert respond["parameters"]["options"]["responseCode"] == 202


def test_n8n_status_workflow_returns_curator_ranked_top_five():
    workflow = _load(STATUS)
    assert workflow["active"] is False
    names = [node["name"] for node in workflow["nodes"]]
    assert names == ["Webhook", "Validate Job", "Get Status", "Curate Result", "Respond"]
    code = next(node for node in workflow["nodes"] if node["name"] == "Curate Result")["parameters"]["jsCode"]
    assert "curator_score" in code
    assert "relevance_score" in code
    assert "slice(0,5)" in code


def test_n8n_templates_use_env_references_and_no_live_secrets():
    text = SUBMIT.read_text(encoding="utf-8") + STATUS.read_text(encoding="utf-8")
    assert "$env.RESEARCH_GATEWAY_URL" in text
    assert "$env.RESEARCH_GATEWAY_TOKEN" in text
    lowered = text.lower()
    assert "ghp_" not in lowered
    assert "sk-" not in lowered
    assert "youtube cookie" not in lowered


def test_n8n_status_validates_job_id_before_gateway_call():
    workflow = _load(STATUS)
    validator = next(node for node in workflow["nodes"] if node["name"] == "Validate Job")
    assert "A-Za-z0-9._:-" in validator["parameters"]["jsCode"]
    status = next(node for node in workflow["nodes"] if node["name"] == "Get Status")
    assert "/v1/jobs/" in status["parameters"]["url"]
