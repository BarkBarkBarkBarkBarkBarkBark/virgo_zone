from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("virgozone.citations")

ACTIONS = {
    "initialize", "sync-now", "sync-status", "sync-conflicts", "sync-resolve", "background-tick",
    "dashboard", "create-person", "search-persons", "create-violation", "list-violations",
    "issue", "issue-for-attendee", "search", "find-citations", "manage-citation", "get", "edit",
    "add-remedy", "edit-remedy", "complete-remedy", "resolve", "reopen", "void", "overdue",
    "history", "party-settings", "export",
}
MUTATING = {
    "create-person", "create-violation", "issue", "issue-for-attendee", "manage-citation", "edit",
    "add-remedy", "edit-remedy", "complete-remedy", "resolve", "reopen", "void", "party-settings",
    "sync-resolve",
}


class CitationsUnavailable(RuntimeError):
    """The citations source package is not importable or not configured."""


class CitationsContext:
    """Implements the extension Context protocol over a private VirgoZone directory."""

    def __init__(self, root: Path, allow_network: bool) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.allow_network = allow_network

    def data_path(self, relative: str) -> str:
        path = Path(relative)
        if not relative or path.is_absolute() or "\\" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
            raise ValueError("Use a relative citations data path.")
        target = self.root / path
        if not target.resolve().is_relative_to(self.root):
            raise ValueError("Citations data path escapes the data directory.")
        current = target
        while current != self.root:
            if current.is_symlink():
                raise ValueError("Symlinked citations data paths are not permitted.")
            current = current.parent
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        return str(target)

    def read_data(self, name: str) -> str | None:
        path = Path(self.data_path(name))
        return path.read_text(encoding="utf-8") if path.exists() else None

    def write_data(self, name: str, text: str) -> None:
        target = Path(self.data_path(name))
        fd, temporary = tempfile.mkstemp(prefix=".citations-", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def delete_data(self, name: str) -> None:
        Path(self.data_path(name)).unlink(missing_ok=True)

    def require_network(self) -> None:
        if not self.allow_network:
            raise PermissionError("CITATIONS_ALLOW_NETWORK is false; remote synchronization is disabled.")

    def log(self, event: str, metadata: dict) -> None:
        # Mirror the host privacy rule: event names and metadata field names only.
        LOGGER.debug("%s %s", event, sorted(metadata))


def _import_citations(source: Path | None):
    """Import the extension's `citations` package and `main.run` from CITATIONS_SOURCE."""
    if source is not None:
        source = source.resolve()
        if (source / "extension" / "extension.yaml").is_file():
            source = source / "extension"
        if not (source / "citations" / "__init__.py").is_file() or not (source / "main.py").is_file():
            raise CitationsUnavailable(f"CITATIONS_SOURCE does not contain the citations extension: {source}")
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
    if source is None:
        raise CitationsUnavailable("CITATIONS_SOURCE is not set; point it at the hosaka_citations checkout.")
    try:
        importlib.import_module("citations")
        spec = importlib.util.spec_from_file_location("virgozone_citations_entry", source / "main.py")
        assert spec is not None and spec.loader is not None
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
    except ImportError as exc:
        raise CitationsUnavailable(f"Cannot import the citations extension: {exc}") from exc
    if not hasattr(entry, "run"):
        raise CitationsUnavailable("The citations entrypoint main.run was not found; set CITATIONS_SOURCE.")
    return entry.run


class CitationsBridge:
    """Serialized access to the extension API with VirgoZone-owned configuration."""

    def __init__(self, source: Path | None, data_dir: Path, remote: dict[str, Any], allow_network: bool) -> None:
        self.source = source
        self.data_dir = data_dir
        self.remote = remote
        self.allow_network = allow_network
        self._lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._run = None
        self._error: str | None = None
        self.context: CitationsContext | None = None

    @property
    def available(self) -> bool:
        return self._run is not None

    @property
    def error(self) -> str | None:
        return self._error

    def initialize(self) -> None:
        try:
            self._run = _import_citations(self.source)
        except CitationsUnavailable as exc:
            self._error = str(exc)
            LOGGER.warning("Citations integration disabled: %s", exc)
            return
        self.context = CitationsContext(self.data_dir, self.allow_network)
        self._apply_remote_config()
        result = self.run("initialize", {})
        if not result.get("success"):
            self._error = result.get("error") or "Citations database initialization failed."
            LOGGER.error("Citations initialization failed: %s", self._error)
            self._run = None

    def _apply_remote_config(self) -> None:
        """Write citations-config.json from VirgoZone settings without touching unknown fields."""
        from citations.config import load_config
        from citations.database import encoded
        from citations.validation import DomainError

        assert self.context is not None
        current = load_config(self.context, validate_remote=False)
        changes = {key: value for key, value in self.remote.items() if value is not None}
        if not changes:
            return
        merged = {**current, **changes}
        previous = self.context.read_data("citations-config.json")
        self.context.write_data("citations-config.json", encoded(merged))
        try:
            load_config(self.context)
        except DomainError as exc:
            if previous is not None:
                self.context.write_data("citations-config.json", previous)
            else:
                self.context.delete_data("citations-config.json")
            raise CitationsUnavailable(f"Invalid citations remote configuration: {exc}") from exc

    def run(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._run is None or self.context is None:
            raise CitationsUnavailable(self._error or "Citations integration is not initialized.")
        if action not in ACTIONS:
            raise ValueError(f"Unknown citations action: {action}")
        if action in {"sync-now", "background-tick"}:
            with self._sync_lock:
                return self._run(action, params or {}, self.context)
        if action in MUTATING:
            with self._lock:
                return self._run(action, params or {}, self.context)
        return self._run(action, params or {}, self.context)

    def login(self, email: str, password: str) -> None:
        """Server-side Supabase user login; the password is never stored."""
        if self._run is None or self.context is None:
            raise CitationsUnavailable(self._error or "Citations integration is not initialized.")
        from citations.config import load_config
        from citations.supabase import Supabase

        with self._sync_lock:
            Supabase(self.context, load_config(self.context)).login(email, password)

    def session_present(self) -> bool:
        if self.context is None:
            return False
        raw = self.context.read_data("supabase-auth.json")
        if raw is None:
            return False
        try:
            return isinstance(json.loads(raw).get("refresh_token"), str)
        except (ValueError, AttributeError):
            return False
