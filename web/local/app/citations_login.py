"""Sign VirgoZone's citations replica in to the shared Supabase workspace.

Usage (from the virgo_zone checkout, with the same env as the server):

    python -m app.citations_login

The organizer password is read from an interactive prompt only. It is never
written to disk; only the resulting session tokens are stored (mode 0600) under
DATA_DIR/citations/supabase-auth.json.
"""
from __future__ import annotations

import getpass
import sys

from app.citations.bridge import CitationsBridge, CitationsUnavailable
from app.settings import get_settings


def main() -> int:
    settings = get_settings()
    bridge = CitationsBridge(
        settings.citations_source,
        settings.resolved_citations_data_dir,
        settings.citations_remote_config(),
        settings.citations_allow_network,
    )
    bridge.initialize()
    if not bridge.available:
        print(f"Citations integration unavailable: {bridge.error}", file=sys.stderr)
        return 2
    if not sys.stdin.isatty():
        print("Refusing to read a password from a pipe; run interactively.", file=sys.stderr)
        return 2
    email = input("Organizer email: ").strip()
    password = getpass.getpass("Organizer password (not echoed, not stored): ")
    try:
        bridge.login(email, password)
    except CitationsUnavailable as exc:
        print(f"Login failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # SyncError and friends come from the extension
        print(f"Login failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        del password
    result = bridge.run("sync-now", {})
    status = result.get("record") or {}
    print("Signed in. Session stored in", bridge.context.data_path("supabase-auth.json"))
    print(f"Sync: success={result.get('success')} remote_cursor={status.get('remote_cursor')} "
          f"pending={status.get('pending_changes')} error={status.get('last_error')}")
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
