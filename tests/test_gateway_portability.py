import errno
import io
import json
from urllib.error import URLError
from unittest.mock import Mock

import pytest

from app import launcher
from app import settings as settings_module


def test_installed_package_requires_explicit_data_location(monkeypatch):
    monkeypatch.setattr(settings_module, "SOURCE_CHECKOUT", False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("HOSAKA_EXTENSION_DATA", raising=False)
    with pytest.raises(ValueError, match="requires explicit DATA_DIR"):
        settings_module.Settings.from_env()


def test_gateway_refuses_silently_switching_existing_database(tmp_path, monkeypatch):
    source = tmp_path / "source"
    legacy = source / "data"
    legacy.mkdir(parents=True)
    (legacy / "virgo-zone.db").touch()
    monkeypatch.setattr(settings_module, "PROJECT_ROOT", source)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setenv("HOSAKA_EXTENSION_DATA", str(tmp_path / "new-data"))
    with pytest.raises(ValueError, match="no data was moved"):
        settings_module.Settings.from_env()
    monkeypatch.setenv("DATA_DIR", str(legacy))
    assert settings_module.Settings.from_env().data_dir == legacy


def test_launcher_reuses_healthy_gateway_without_spawning(monkeypatch):
    monkeypatch.setattr("sys.argv", ["virgozone-start", "--no-browser"])
    opener = Mock()
    opener.open.return_value = io.BytesIO(json.dumps({"service": "hosaka-gateway"}).encode())
    monkeypatch.setattr(launcher, "build_opener", lambda *args: opener)
    popen = Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    launcher.main()
    popen.assert_not_called()


def test_launcher_does_not_confuse_timeout_with_absent_gateway(monkeypatch):
    monkeypatch.setattr("sys.argv", ["virgozone-start", "--no-browser"])
    opener = Mock()
    opener.open.side_effect = URLError(TimeoutError(errno.ETIMEDOUT, "synthetic timeout"))
    monkeypatch.setattr(launcher, "build_opener", lambda *args: opener)
    popen = Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    with pytest.raises(SystemExit, match="Cannot check gateway readiness"):
        launcher.main()
    popen.assert_not_called()


def test_launcher_waits_for_readiness_before_opening_browser(monkeypatch):
    monkeypatch.setattr("sys.argv", ["virgozone-start"])
    opener = Mock()
    opener.open.side_effect = [
        URLError(ConnectionRefusedError(errno.ECONNREFUSED, "synthetic refusal")),
        io.BytesIO(json.dumps({"service": "hosaka-gateway"}).encode()),
    ]
    monkeypatch.setattr(launcher, "build_opener", lambda *args: opener)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/synthetic/hosaka")
    process = Mock()
    process.poll.side_effect = [None, 0]
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda command: process)
    browser = Mock()
    monkeypatch.setattr(launcher.webbrowser, "open", browser)
    launcher.main()
    browser.assert_called_once_with("http://127.0.0.1:8086/virgo-zone/")
    process.wait.assert_called_once_with()
