import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / "integrations" / "n8n" / "research-intelligence-staging.json"


def _workflow():
    return json.loads(WORKFLOW.read_text(encoding="utf-8"))


def test_n8n_staging_workflow_is_inactive_and_has_expected_nodes():
    workflow = _workflow()
    assert workflow["active"] is False
    names = [node["name"] for node in workflow["nodes"]]
    assert names == [
        "Webhook",
        "Normalize Request",
        "Research Gateway",
        "Top 5 Curator",
        "Respond",
    ]


def test_n8n_template_uses_env_references_and_contains_no_live_secret():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "$env.RESEARCH_GATEWAY_URL" in text
    assert "$env.RESEARCH_GATEWAY_TOKEN" in text
    lowered = text.lower()
    assert "ghp_" not in lowered
    assert "sk-" not in lowered
    assert "youtube cookie" not in lowered


def test_n8n_template_ranks_with_curator_score_first():
    workflow = _workflow()
    node = next(node for node in workflow["nodes"] if node["name"] == "Top 5 Curator")
    code = node["parameters"]["jsCode"]
    assert "curator_score" in code
    assert "relevance_score" in code
    assert "slice(0,5)" in code


def test_n8n_gateway_posts_agent_request_contract():
    workflow = _workflow()
    gateway = next(node for node in workflow["nodes"] if node["name"] == "Research Gateway")
    params = gateway["parameters"]
    assert params["method"] == "POST"
    assert "/v1/research" in params["url"]
    assert params["sendBody"] is True
