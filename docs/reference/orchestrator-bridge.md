# Orchestrator bridge

`orchestrator_bridge.py` is the machine-facing adapter for n8n, Cloudflare,
RDC, and other control-plane callers. It accepts one bounded JSON request and
returns one JSON response while invoking the normal last30days engine locally.

It does not replace the `/last30days` agent skill. Reasoning hosts should still
build the research intent and query plan; the bridge only provides a stable,
safe execution boundary for automation.

## Request contract

```json
{
  "schema_version": "1.0",
  "request_id": "uaios-research-001",
  "topic": "GitHub AI agents pull request governance",
  "interest_context": ["GitHub Actions", "MCP", "human approval"],
  "sources": ["youtube", "github", "reddit", "hackernews", "grounding"],
  "depth": "deep",
  "days": 30,
  "as_of": "2026-09-17",
  "max_results": 25,
  "plan": {
    "intent": "implementation research",
    "freshness_mode": "balanced_recent",
    "cluster_mode": "themes",
    "subqueries": []
  }
}
```
`interest_context` is deliberately session-scoped. Pass concise, non-sensitive
ranking hints only. Never send raw chat history, private-document text, secrets,
or a durable personal profile through this field.

The bridge currently accepts:

- `topic`: required string, 1-500 characters.
- `request_id`: optional trace identifier using letters, digits, `.`, `_`, `:`, `-`.
- `interest_context`: up to 12 terms, 120 characters each.
- `sources`: up to 16 lowercase source identifiers.
- `depth`: `quick`, `standard`, or `deep`.
- `days`: 1-365; default 30.
- `as_of`: optional `YYYY-MM-DD` research-window endpoint.
- `max_results`: optional integer from 1-200.
- `plan`: optional query-plan JSON object, capped at 64 KiB.

The whole request envelope is capped at 128 KiB.

## Invocation

From a request file:

```powershell
uv run python skills/last30days/scripts/orchestrator_bridge.py --request request.json
```

Or through stdin:

```powershell
Get-Content request.json -Raw | uv run python skills/last30days/scripts/orchestrator_bridge.py
```

## Response contract

Success wraps the versioned agent JSON instead of changing it:

```json
{
  "schema_version": "1.0",
  "request_id": "uaios-research-001",
  "ok": true,
  "engine_schema_version": "1.4",
  "result": {
    "schema_version": "1.4",
    "query": "GitHub AI agents pull request governance",
    "results": []
  }
}
```

Validation failures return `ok: false` with an error code. An invalid request ID
is not reflected back. Engine failures return only a generic error in the JSON
envelope; engine stderr remains stderr for local/operator diagnostics.

## Security boundary

The bridge never builds a shell command string. It calls the engine with an argv
list and no `shell=True`, so topic and interest text stay data even when they
contain shell metacharacters. A caller-supplied `plan` is serialized to a fresh
temporary JSON file created by the bridge; callers cannot provide a plan path.
The temporary file is deleted after execution.

The adapter introduces no credential store, network destination, or persistence
layer. Existing engine source/auth rules still apply.

## Recommended orchestration

Keep reasoning and execution responsibilities separate:

`ChatGPT / reasoning host` → resolves intent and builds `plan`

`n8n / Cloudflare` → validates, routes, schedules, deduplicates, and carries the JSON envelope

`RDC / local executor` → invokes this bridge and the research engine

`agent JSON` → feeds ranking, caching, dashboards, notifications, or later vector indexing

Do not place raw conversation history or provider credentials in the request.
Cloudflare deployment, n8n workflow activation, and new secret configuration are
separate operational changes and are intentionally outside this local adapter.
