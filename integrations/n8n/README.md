# n8n STAGING adapters

These templates connect n8n to the asynchronous Research Intelligence gateway
without embedding secrets or shell commands in workflow JSON.

Submit flow:

Webhook -> Normalize Request -> Submit Job -> Respond 202

Status flow:

Webhook -> Validate Job -> Get Status -> Curate Result -> Respond

Both workflows are intentionally inactive in source control. Configure the n8n
runtime with:

- RESEARCH_GATEWAY_URL
- RESEARCH_GATEWAY_TOKEN

The gateway accepts POST /v1/research and returns a queued job id. Results are
read later from GET /v1/jobs/:job_id. This avoids holding one HTTP request open
while local transcript research runs for minutes.

Do not place browser cookies, YouTube session data, API keys, or raw chat history
in workflow JSON. interest_context should contain concise, non-sensitive ranking
hints only.

## Submit request example

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

The submit workflow returns HTTP 202 with job_id. Call the status workflow with
`?job_id=<id>`. When the gateway reports completed, it returns up to five
recommendations sorted by curator_score with privacy-safe recommendation reasons.

These templates do not activate n8n, create credentials, expose the local PC,
or deploy Cloudflare resources.
