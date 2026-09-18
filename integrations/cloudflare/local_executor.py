#!/usr/bin/env python3
"""Outbound-only RDC executor for the Research Intelligence STAGING gateway."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "skills" / "last30days" / "scripts" / "orchestrator_bridge.py"


def _request(url: str, token: str, method: str = "GET", payload=None, executor_id="rdc-local"):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}", "X-Executor-Id": executor_id}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _run_bridge(request_payload: dict) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(request_payload, handle, ensure_ascii=False)
        request_path = Path(handle.name)
    try:
        child_env = os.environ.copy()
        local_bin = Path.home() / ".local" / "bin"
        child_env["PATH"] = str(local_bin) + os.pathsep + child_env.get("PATH", "")
        child_env.setdefault("FROM_BROWSER", "off")
        completed = subprocess.run(
            [sys.executable, str(BRIDGE), "--request", str(request_path)],
            cwd=ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        if completed.returncode != 0:
            return {"ok": False, "error": "bridge_failed"}
        try:
            envelope = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return {"ok": False, "error": "invalid_bridge_output"}
        if not envelope.get("ok"):
            return {"ok": False, "error": "research_failed"}
        return {"ok": True, "result": envelope.get("result") or {}}
    finally:
        request_path.unlink(missing_ok=True)


def run_once(gateway: str, token: str, executor_id: str) -> bool:
    claim = _request(gateway.rstrip("/") + "/v1/executor/claim", token, method="POST", payload={}, executor_id=executor_id)
    job = claim.get("job") if isinstance(claim, dict) else None
    if not job:
        return False
    job_id = job["job_id"]
    outcome = _run_bridge(job["request"])
    result_url = gateway.rstrip("/") + f"/v1/executor/jobs/{job_id}/result"
    _request(result_url, token, method="POST", payload=outcome, executor_id=executor_id)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default=os.environ.get("RESEARCH_GATEWAY_URL"))
    parser.add_argument("--token", default=os.environ.get("RESEARCH_EXECUTOR_TOKEN"))
    parser.add_argument("--executor-id", default=os.environ.get("RESEARCH_EXECUTOR_ID", "rdc-local"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    if not args.gateway or not args.token:
        parser.error("gateway and executor token are required")
    while True:
        try:
            handled = run_once(args.gateway, args.token, args.executor_id)
        except (urllib.error.URLError, TimeoutError):
            handled = False
        if args.once:
            return 0
        if not handled:
            time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
