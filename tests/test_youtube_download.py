import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_reach.youtube_download import (
    YouTubeDownloadError,
    build_command,
    chrome_cookie_db,
    download_youtube,
    ensure_cookie_access,
)


def test_build_command_contains_verified_chain(tmp_path):
    cmd = build_command(
        "https://www.youtube.com/watch?v=test",
        output_dir=tmp_path,
        quality=720,
        cookie_source="chrome:Profile 1",
    )

    assert cmd[0] == "yt-dlp"
    assert "--cookies-from-browser" in cmd
    assert cmd[cmd.index("--cookies-from-browser") + 1] == "chrome:Profile 1"
    assert "--remote-components" in cmd
    assert cmd[cmd.index("--remote-components") + 1] == "ejs:github"
    assert "youtube:player-client=mweb" in cmd
    assert "--cache-dir" in cmd
    assert str(tmp_path / ".cache" / "yt-dlp") in cmd
    assert "bv*[ext=mp4][height<=720]" in cmd[cmd.index("--format") + 1]


def test_build_command_can_simulate_without_cookies(tmp_path):
    cmd = build_command(
        "https://www.youtube.com/watch?v=test",
        output_dir=tmp_path,
        quality=360,
        cookie_source=None,
        no_cookies=True,
        simulate=True,
    )

    assert "--cookies-from-browser" not in cmd
    assert "--simulate" in cmd
    assert cmd[-1] == "https://www.youtube.com/watch?v=test"


def test_chrome_cookie_db_maps_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert chrome_cookie_db("chrome:Profile 2") == (
        tmp_path
        / "Google"
        / "Chrome"
        / "User Data"
        / "Profile 2"
        / "Network"
        / "Cookies"
    )
    assert chrome_cookie_db("firefox:default") is None


def test_locked_cookie_db_fails_early(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    db = chrome_cookie_db("chrome:Profile 1")
    assert db is not None
    db.parent.mkdir(parents=True)
    db.write_bytes(b"fake")

    with patch.object(Path, "open", side_effect=PermissionError("locked")):
        with pytest.raises(YouTubeDownloadError, match="被占用"):
            ensure_cookie_access("chrome:Profile 1")


def test_download_defaults_to_profile_2(monkeypatch, tmp_path):
    captured = {}

    class ConfigWithoutCookieSource:
        @staticmethod
        def get(_key, default=None):
            return default

    def fake_build_command(*_args, **kwargs):
        captured.update(kwargs)
        return ["yt-dlp"]

    monkeypatch.setattr(
        "agent_reach.youtube_download.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    monkeypatch.setattr(
        "agent_reach.youtube_download.ensure_cookie_access",
        lambda source: captured.update(checked=source),
    )
    monkeypatch.setattr(
        "agent_reach.youtube_download.build_command",
        fake_build_command,
    )
    monkeypatch.setattr(
        "agent_reach.youtube_download.subprocess.run",
        lambda cmd: subprocess.CompletedProcess(cmd, 0),
    )

    download_youtube(
        "https://www.youtube.com/watch?v=test",
        output_dir=tmp_path,
        simulate=True,
        config=ConfigWithoutCookieSource(),
    )

    assert captured["cookie_source"] == "chrome:Profile 2"
    assert captured["checked"] == "chrome:Profile 2"
