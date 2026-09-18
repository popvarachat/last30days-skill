const JSON_HEADERS = { "content-type": "application/json; charset=utf-8" };

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

function bearer(request) {
  const value = request.headers.get("authorization") || "";
  return value.startsWith("Bearer ") ? value.slice(7) : "";
}

function authorized(request, expected) {
  const actual = bearer(request);
  return Boolean(expected && actual && actual === expected);
}

function nowIso() {
  return new Date().toISOString();
}

function validJobId(value) {
  return typeof value === "string" && /^[A-Za-z0-9._:-]{1,128}$/.test(value);
}

function makeJobId() {
  return "research-" + crypto.randomUUID();
}
async function readJsonBounded(request, env) {
  const limit = Number(env.MAX_REQUEST_BYTES || 131072);
  const length = Number(request.headers.get("content-length") || 0);
  if (length && length > limit) throw new Error("request_too_large");
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > limit) throw new Error("request_too_large");
  let value;
  try { value = JSON.parse(text); } catch { throw new Error("invalid_json"); }
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid_request");
  return value;
}

function validateResearchRequest(body) {
  if (body.schema_version !== "1.0") return "unsupported_schema_version";
  if (typeof body.topic !== "string" || !body.topic.trim() || body.topic.length > 500) return "invalid_topic";
  if (body.request_id != null && !validJobId(body.request_id)) return "invalid_request_id";
  if (body.interest_context != null && (!Array.isArray(body.interest_context) || body.interest_context.length > 12)) return "invalid_interest_context";
  return null;
}

async function submitJob(request, env) {
  if (!authorized(request, env.CLIENT_API_TOKEN)) return json({ ok: false, error: "unauthorized" }, 401);
  let body;
  try { body = await readJsonBounded(request, env); } catch (error) {
    const code = String(error.message || "invalid_request");
    return json({ ok: false, error: code }, code === "request_too_large" ? 413 : 400);
  }
  const validation = validateResearchRequest(body);
  if (validation) return json({ ok: false, error: validation }, 400);
  const jobId = validJobId(body.request_id) ? body.request_id : makeJobId();
  const now = nowIso();
  const insert = await env.DB.prepare(
    "INSERT INTO research_jobs (job_id,request_json,status,created_at,updated_at) VALUES (?1,?2,'queued',?3,?3) ON CONFLICT(job_id) DO NOTHING"
  ).bind(jobId, JSON.stringify(body), now).run();
  if ((insert.meta?.changes || 0) === 0) {
    const existing = await env.DB.prepare("SELECT status FROM research_jobs WHERE job_id=?1").bind(jobId).first();
    return json({ ok: true, job_id: jobId, status: existing?.status || "unknown", duplicate: true }, 202);
  }
  return json({ ok: true, job_id: jobId, status: "queued" }, 202);
}

async function jobStatus(request, env, jobId) {
  if (!authorized(request, env.CLIENT_API_TOKEN)) return json({ ok: false, error: "unauthorized" }, 401);
  if (!validJobId(jobId)) return json({ ok: false, error: "invalid_job_id" }, 400);
  const row = await env.DB.prepare(
    "SELECT job_id,status,result_json,error_code,created_at,updated_at FROM research_jobs WHERE job_id=?1"
  ).bind(jobId).first();
  if (!row) return json({ ok: false, error: "not_found" }, 404);
  const response = { ok: true, job_id: row.job_id, status: row.status, created_at: row.created_at, updated_at: row.updated_at };
  if (row.status === "completed" && row.result_json) response.result = JSON.parse(row.result_json);
  if (row.status === "failed") response.error = row.error_code || "executor_failed";
  return json(response);
}

async function claimJob(request, env) {
  if (!authorized(request, env.EXECUTOR_API_TOKEN)) return json({ ok: false, error: "unauthorized" }, 401);
  const executorId = (request.headers.get("x-executor-id") || "rdc-local").slice(0, 128);
  const now = nowIso();
  const lease = new Date(Date.now() + 10 * 60 * 1000).toISOString();
  const candidate = await env.DB.prepare(
    "SELECT job_id FROM research_jobs WHERE status='queued' OR (status='running' AND lease_expires_at < ?1) ORDER BY created_at LIMIT 1"
  ).bind(now).first();
  if (!candidate) return json({ ok: true, job: null });
  const claimed = await env.DB.prepare(
    "UPDATE research_jobs SET status='running',claimed_at=?1,lease_expires_at=?2,executor_id=?3,updated_at=?1 WHERE job_id=?4 AND (status='queued' OR (status='running' AND lease_expires_at < ?1))"
  ).bind(now, lease, executorId, candidate.job_id).run();
  if ((claimed.meta?.changes || 0) !== 1) return json({ ok: true, job: null });
  const row = await env.DB.prepare("SELECT job_id,request_json,lease_expires_at FROM research_jobs WHERE job_id=?1").bind(candidate.job_id).first();
  return json({ ok: true, job: { job_id: row.job_id, request: JSON.parse(row.request_json), lease_expires_at: row.lease_expires_at } });
}

async function completeJob(request, env, jobId) {
  if (!authorized(request, env.EXECUTOR_API_TOKEN)) return json({ ok: false, error: "unauthorized" }, 401);
  if (!validJobId(jobId)) return json({ ok: false, error: "invalid_job_id" }, 400);
  let body;
  try { body = await readJsonBounded(request, { ...env, MAX_REQUEST_BYTES: 1048576 }); } catch (error) {
    return json({ ok: false, error: String(error.message || "invalid_request") }, 400);
  }
  const now = nowIso();
  const succeeded = body.ok === true && body.result && typeof body.result === "object";
  const resultJson = succeeded ? JSON.stringify(body.result) : null;
  const errorCode = succeeded ? null : String(body.error || "executor_failed").slice(0, 128);
  const updated = await env.DB.prepare(
    "UPDATE research_jobs SET status=?1,result_json=?2,error_code=?3,updated_at=?4,lease_expires_at=NULL WHERE job_id=?5 AND status='running'"
  ).bind(succeeded ? "completed" : "failed", resultJson, errorCode, now, jobId).run();
  if ((updated.meta?.changes || 0) !== 1) return json({ ok: false, error: "job_not_running" }, 409);
  return json({ ok: true, job_id: jobId, status: succeeded ? "completed" : "failed" });
}
export default {
  async fetch(request, env) {
    if ((env.ENVIRONMENT || "staging") !== "staging") {
      return json({ ok: false, error: "staging_only" }, 503);
    }
    const url = new URL(request.url);
    const path = url.pathname;
    if (request.method === "GET" && path === "/health") {
      return json({ ok: true, service: "research-intelligence-gateway", environment: "staging" });
    }
    if (request.method === "POST" && path === "/v1/research") {
      return submitJob(request, env);
    }
    const statusMatch = path.match(/^\/v1\/jobs\/([^/]+)$/);
    if (request.method === "GET" && statusMatch) {
      return jobStatus(request, env, decodeURIComponent(statusMatch[1]));
    }
    if (request.method === "POST" && path === "/v1/executor/claim") {
      return claimJob(request, env);
    }
    const resultMatch = path.match(/^\/v1\/executor\/jobs\/([^/]+)\/result$/);
    if (request.method === "POST" && resultMatch) {
      return completeJob(request, env, decodeURIComponent(resultMatch[1]));
    }
    return json({ ok: false, error: "not_found" }, 404);
  },
};
