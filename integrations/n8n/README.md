# n8n STAGING adapter

This template exposes the research engine to n8n without embedding secrets or
shell commands in the workflow.

Flow:

Webhook -> Normalize Request -> Research Gateway -> Top 5 Curator -> Respond

The workflow is intentionally inactive in source control. Configure the runtime
with two environment variables in the n8n host:

- RESEARCH_GATEWAY_URL
- RESEARCH_GATEWAY_TOKEN

The gateway must expose POST /v1/research and return the orchestrator bridge
response envelope. The workflow expects agent JSON schema 1.5 or later.

Do not place browser cookies, YouTube session data, API keys, or raw chat history
in the workflow JSON. interest_context should contain only concise non-sensitive
ranking hints.

## Request example

```json
{
  "request_id": "research-001",
  "topic": "GitHub AI agents pull request governance",
  "interest_context": ["GitHub Actions", "MCP", "human approval"],
  "sources": ["youtube"],
  "depth": "deep",
  "days": 30,
  "max_results": 25
}
```

The response contains up to five recommendations sorted by curator_score, with
topic and personal-fit diagnostics and a privacy-safe recommendation reason.

This template does not activate n8n, create credentials, expose the local
machine, or deploy a Cloudflare Worker. Those are separate operational changes.
