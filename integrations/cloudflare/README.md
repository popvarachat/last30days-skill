# Cloudflare Research Gateway STAGING

This integration provides an outbound-only job broker between n8n and the local
Research Intelligence executor. The local PC never exposes an inbound port.

Flow:

n8n -> POST /v1/research -> Cloudflare Worker + D1 -> queued job
RDC local_executor.py -> POST /v1/executor/claim -> runs orchestrator_bridge.py
RDC -> POST /v1/executor/jobs/:id/result -> D1 stores result
n8n/ChatGPT -> GET /v1/jobs/:id -> completed result

Authentication is split by role:

- CLIENT_API_TOKEN: submit/read jobs from n8n or another trusted client.
- EXECUTOR_API_TOKEN: claim/complete jobs from the RDC executor only.

Both are Worker secrets. Never commit them, browser cookies, YouTube sessions,
or raw chat history.

## STAGING setup

Copy `wrangler.toml.example` to a local ignored `wrangler.toml`, create a STAGING
D1 database, apply `schema.sql`, then configure the two secrets. Do not reuse a
production database or production token.

The Worker refuses to serve the research API when `ENVIRONMENT` is not
`staging`. This repository change does not create D1, set secrets, or deploy the
Worker.

Run the local executor with environment variables instead of command-history
secrets:

```powershell
$env:RESEARCH_GATEWAY_URL = "https://<staging-worker>"
$env:RESEARCH_EXECUTOR_TOKEN = "<secret>"
python integrations/cloudflare/local_executor.py --once
```

For continuous operation, omit `--once`. The executor only makes outbound HTTPS
requests and invokes the existing bounded JSON bridge locally.
