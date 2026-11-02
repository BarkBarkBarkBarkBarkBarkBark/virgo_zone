"""Hosaka API v1 entrypoint for the VirgoZone extension (stdlib only).

Reads the VirgoZone party server over loopback HTTP. Nothing here mutates
citations; organizer actions stay on the authenticated web page.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8069"
CONFIG_NAME = "virgo-zone-config.json"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
TIMEOUT_SECONDS = 6


def _result(success: bool, message: str, error: str | None = None, **extra) -> dict:
    return {"success": success, "message": message, "error": error, **extra}


def _base_url(context) -> str:
    raw = context.read_data(CONFIG_NAME)
    if raw is None:
        return DEFAULT_BASE_URL
    try:
        value = json.loads(raw).get("base_url", DEFAULT_BASE_URL)
    except (ValueError, AttributeError):
        return DEFAULT_BASE_URL
    return value if _valid_base_url(value) else DEFAULT_BASE_URL


def _valid_base_url(value: str) -> bool:
    parts = urllib.parse.urlsplit(value)
    return (
        parts.scheme == "http"
        and parts.hostname in LOOPBACK_HOSTS
        and not parts.username and not parts.password
        and parts.path in ("", "/") and not parts.query and not parts.fragment
    )


def _fetch(context, path: str, query: dict | None = None) -> dict:
    context.require_network()
    headers = {"Accept": "application/json"}
    runtime = context.read_data("web-runtime.json")
    if runtime is not None:
        settings = json.loads(runtime)
        origin, token = settings["origin"], settings["token"]
        if not _valid_base_url(origin) or not isinstance(token, str) or not 32 <= len(token) <= 128:
            raise ValueError("Invalid local web runtime.")
        headers["X-Hosaka-Gateway-Token"] = token
    else:
        origin = _base_url(context)
    url = origin.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode({key: value for key, value in query.items() if value not in (None, "")})
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read(1_048_576).decode("utf-8"))


def _status(context) -> dict:
    health = _fetch(context, "/api/status")
    citations = _fetch(context, "/api/citations/status")
    sync = citations.get("synchronization") or {}
    dashboard = citations.get("dashboard") or {}
    rows = [
        {"name": "virgozone", "value": "online"},
        {"name": "websocket clients", "value": str(health.get("connected_clients", health.get("websocket_clients", "?")))},
        {"name": "citations available", "value": str(citations.get("available"))},
        {"name": "organizer session", "value": "present" if citations.get("session_present") else "missing"},
        {"name": "sync enabled", "value": str(sync.get("enabled"))},
        {"name": "pending changes", "value": str(sync.get("pending_changes", "—"))},
        {"name": "unresolved conflicts", "value": str(sync.get("unresolved_conflicts", "—"))},
        {"name": "remote cursor", "value": str(sync.get("remote_cursor", "—"))},
        {"name": "last successful sync", "value": str(sync.get("last_successful_sync") or "never")},
        {"name": "last error", "value": str(sync.get("last_error") or "none")},
        *[{"name": key, "value": str(dashboard.get(key, "—"))} for key in ("open", "overdue", "resolved", "void", "due_soon", "incomplete_required_remedies")],
    ]
    if not citations.get("available"):
        return _result(False, "VirgoZone is online but citations are not configured there.", citations.get("error") or "Citations unavailable.", rows=rows)
    if sync.get("last_error"):
        return _result(False, "VirgoZone online; citations sync reports an error.", str(sync["last_error"]), rows=rows)
    return _result(True, f"VirgoZone online. {dashboard.get('open', 0)} open citation(s), {dashboard.get('overdue', 0)} overdue.", rows=rows)


def _wall(context, params: dict) -> dict:
    payload = _fetch(context, "/api/citations/wall", {
        "q": params.get("query", ""), "status": params.get("status", "open"), "sort": params.get("sort", "date"),
        "order": params.get("order", "desc"), "overdue_only": "true" if params.get("overdue_only") else "",
    })
    rows = [
        {
            "offender": row.get("offender", ""), "violation": row.get("violation", ""), "status": row.get("status", ""),
            "overdue": "yes" if row.get("overdue") else "", "issued_at": row.get("issued_at", ""),
            "due_at": row.get("due_at") or "", "comment_count": row.get("comment_count", 0),
            "citation_number": row.get("citation_number", ""),
        }
        for row in payload.get("items", [])
    ]
    return _result(True, f"{len(rows)} citation(s) on the wall. Open /citations in a browser to comment or act.", rows=rows)


def _configure(context, params: dict) -> dict:
    base_url = params["base_url"].strip().rstrip("/")
    if not _valid_base_url(base_url):
        return _result(False, "Configuration rejected.", "Base URL must be plain http:// on 127.0.0.1, localhost or ::1 without path, query or credentials.")
    context.write_data(CONFIG_NAME, json.dumps({"base_url": base_url}))
    return _result(True, f"VirgoZone base URL stored: {base_url}")


def run(action: str, params: dict, context) -> dict:
    try:
        if action == "status":
            return _status(context)
        if action == "wall":
            return _wall(context, params)
        if action == "configure":
            return _configure(context, params)
        return _result(False, "Unknown action.", f"Unsupported action: {action}")
    except PermissionError as exc:
        return _result(False, "Network permission required.", str(exc))
    except urllib.error.HTTPError as exc:
        return _result(False, "VirgoZone rejected the request.", f"HTTP {exc.code} from VirgoZone.")
    except (urllib.error.URLError, TimeoutError, OSError):
        return _result(False, "VirgoZone unreachable.", "Could not reach the VirgoZone server over loopback; is it running on the configured port?")
    except ValueError:
        return _result(False, "Invalid response.", "VirgoZone returned a response that was not valid JSON.")
