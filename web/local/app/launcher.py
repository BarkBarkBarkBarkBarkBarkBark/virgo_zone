"""Compatibility command for the canonical local gateway."""
from __future__ import annotations

import argparse
import errno
import json
import shutil
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import build_opener, ProxyHandler
import webbrowser


def healthy(opener, origin):
    with opener.open(origin + "/health", timeout=2) as response:
        if json.load(response).get("service") != "hosaka-gateway":
            raise SystemExit("Another service occupies the gateway port. Choose --port explicitly.")


def main():
    parser = argparse.ArgumentParser(description="Start/reuse Hosaka Gateway and open VirgoZone.")
    parser.add_argument("--port", type=int, default=8086)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use an unprivileged port between 1024 and 65535.")
    origin = f"http://127.0.0.1:{args.port}"
    opener = build_opener(ProxyHandler({}))
    process = None
    try:
        healthy(opener, origin)
    except URLError as exc:
        if not isinstance(exc.reason, OSError) or exc.reason.errno != errno.ECONNREFUSED:
            raise SystemExit(f"Cannot check gateway readiness: {exc.reason}") from exc
        executable = shutil.which("hosaka")
        if executable is None:
            raise SystemExit("Install Hosaka with --gateway first.")
        process = subprocess.Popen([executable, "gateway", "serve", "--port", str(args.port)])
    try:
        if process is not None:
            deadline = time.monotonic() + 20
            while True:
                if process.poll() is not None:
                    raise SystemExit("Gateway startup failed. Run hosaka gateway configure and inspect the error above.")
                try:
                    healthy(opener, origin)
                    break
                except URLError as exc:
                    if not isinstance(exc.reason, OSError) or exc.reason.errno != errno.ECONNREFUSED:
                        raise SystemExit(f"Cannot check gateway readiness: {exc.reason}") from exc
                    if time.monotonic() >= deadline:
                        raise SystemExit("Gateway readiness timed out; inspect the error above.") from exc
                    time.sleep(.1)
        print(f"VirgoZone: {origin}/virgo-zone/ (gateway sign-in required)", flush=True)
        if not args.no_browser:
            webbrowser.open(origin + "/virgo-zone/")
        if process is not None:
            process.wait()
    except KeyboardInterrupt:
        print("\nStopping the gateway started by this command.", file=sys.stderr)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
