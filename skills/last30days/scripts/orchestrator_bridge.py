#!/usr/bin/env python3
"""Safe JSON bridge from orchestrators to the last30days engine.

Designed for n8n, Cloudflare, RDC, and other control-plane callers that need
one stable request/response contract without constructing shell commands.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

REQUEST_SCHEMA_VERSION = "1.0"
RESPONSE_SCHEMA_VERSION = "1.0"
SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE = SCRIPT_DIR / "last30days.py"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SOURCE_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


class RequestError(ValueError):
    pass


def _bounded_text(value: Any, field: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise RequestError(f"{field} must be a string")
    text = value.strip()
    if not text or len(text) > limit:
        raise RequestError(f"{field} must contain 1-{limit} characters")
    if any(ord(char) < 32 for char in text):
        raise RequestError(f"{field} must not contain control characters")
    return text


def _string_list(value: Any, field: str, *, max_items: int, max_len: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > max_items:
        raise RequestError(f"{field} must be a list with at most {max_items} items")
    result: list[str] = []
    for item in value:
        text = _bounded_text(item, field, limit=max_len)
        if text not in result:
            result.append(text)
    return result


def validate_request(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RequestError("request must be a JSON object")
    allowed = {"schema_version", "request_id", "topic", "interest_context", "sources", "depth", "days", "as_of", "max_results", "plan"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise RequestError(f"unsupported request fields: {', '.join(unknown)}")
    version = payload.get("schema_version", REQUEST_SCHEMA_VERSION)
    if version != REQUEST_SCHEMA_VERSION:
        raise RequestError(f"unsupported schema_version: {version!r}")

    request_id = payload.get("request_id")
    if request_id is not None:
        request_id = _bounded_text(request_id, "request_id", limit=128)
        if not _REQUEST_ID_RE.fullmatch(request_id):
            raise RequestError("request_id contains unsupported characters")

    topic = _bounded_text(payload.get("topic"), "topic", limit=500)
    interests = _string_list(
        payload.get("interest_context"), "interest_context", max_items=12, max_len=120
    )
    sources = _string_list(payload.get("sources"), "sources", max_items=16, max_len=32)
    if any(not _SOURCE_RE.fullmatch(source) for source in sources):
        raise RequestError("sources may contain only lowercase source identifiers")

    depth = payload.get("depth", "standard")
    if depth not in {"quick", "standard", "deep"}:
        raise RequestError("depth must be quick, standard, or deep")

    days = payload.get("days", 30)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
        raise RequestError("days must be an integer from 1 to 365")

    as_of = payload.get("as_of")
    if as_of is not None:
        as_of = _bounded_text(as_of, "as_of", limit=10)
        try:
            date.fromisoformat(as_of)
        except ValueError as exc:
            raise RequestError("as_of must be YYYY-MM-DD") from exc

    max_results = payload.get("max_results")
    if max_results is not None:
        if (
            isinstance(max_results, bool)
            or not isinstance(max_results, int)
            or not 1 <= max_results <= 200
        ):
            raise RequestError("max_results must be an integer from 1 to 200")

    plan = payload.get("plan")
    if plan is not None:
        if not isinstance(plan, dict):
            raise RequestError("plan must be a JSON object")
        if len(json.dumps(plan, ensure_ascii=False)) > 65536:
            raise RequestError("plan exceeds the 64 KiB request limit")

    return {
        "schema_version": version,
        "request_id": request_id,
        "topic": topic,
        "interest_context": interests,
        "sources": sources,
        "depth": depth,
        "days": days,
        "as_of": as_of,
        "max_results": max_results,
        "plan": plan,
    }


def build_engine_argv(request: dict[str, Any], plan_path: Path | None = None) -> list[str]:
    argv = [
        sys.executable,
        str(ENGINE),
        request["topic"],
        "--emit=json",
        "--json-profile=agent",
        "--days",
        str(request["days"]),
    ]
    if request["depth"] == "quick":
        argv.append("--quick")
    elif request["depth"] == "deep":
        argv.append("--deep")
    if request["sources"]:
        argv.extend(["--search", ",".join(request["sources"])])
    if request["as_of"]:
        argv.extend(["--as-of", request["as_of"]])
    if request["max_results"] is not None:
        argv.extend(["--max-results", str(request["max_results"])])
    for term in request["interest_context"]:
        argv.extend(["--interest-context", term])
    if plan_path is not None:
        argv.extend(["--plan", str(plan_path)])
    return argv


def run_request(payload: Any) -> tuple[int, dict[str, Any]]:
    try:
        request = validate_request(payload)
    except RequestError as exc:
        return 2, {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "request_id": None,
            "ok": False,
            "error": {"code": "invalid_request", "message": str(exc)},
        }

    plan_file: tempfile.NamedTemporaryFile[str] | None = None
    try:
        plan_path: Path | None = None
        if request["plan"] is not None:
            plan_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", encoding="utf-8", delete=False
            )
            json.dump(request["plan"], plan_file, ensure_ascii=False)
            plan_file.close()
            plan_path = Path(plan_file.name)

        completed = subprocess.run(
            build_engine_argv(request, plan_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            return completed.returncode, {
                "schema_version": RESPONSE_SCHEMA_VERSION,
                "request_id": request["request_id"],
                "ok": False,
                "error": {
                    "code": "engine_failed",
                    "message": "research engine returned a non-zero exit status",
                },
            }
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return 3, {
                "schema_version": RESPONSE_SCHEMA_VERSION,
                "request_id": request["request_id"],
                "ok": False,
                "error": {"code": "invalid_engine_output", "message": "engine did not return JSON"},
            }
        return 0, {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "request_id": request["request_id"],
            "ok": True,
            "engine_schema_version": result.get("schema_version"),
            "result": result,
        }
    finally:
        if plan_file is not None:
            Path(plan_file.name).unlink(missing_ok=True)


def _read_payload(path: str | None) -> Any:
    if path:
        request_path = Path(path)
        if request_path.stat().st_size > 131072:
            raise RequestError("request exceeds the 128 KiB envelope limit")
        text = request_path.read_text(encoding="utf-8")
    else:
        text = sys.stdin.read(131073)
    if len(text.encode("utf-8")) > 131072:
        raise RequestError("request exceeds the 128 KiB envelope limit")
    return json.loads(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run last30days from a safe JSON request envelope")
    parser.add_argument("--request", help="JSON request file; stdin is used when omitted")
    args = parser.parse_args(argv)
    try:
        payload = _read_payload(args.request)
    except (OSError, json.JSONDecodeError, RequestError) as exc:
        code, response = 2, {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "request_id": None,
            "ok": False,
            "error": {"code": "invalid_json", "message": str(exc)},
        }
    else:
        code, response = run_request(payload)
    sys.stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
