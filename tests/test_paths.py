# -*- coding: utf-8 -*-
"""Behavior tests for cross-platform path and remediation helpers."""

import shutil
import subprocess
from pathlib import Path

import pytest

from agent_reach.config import Config
from agent_reach.utils import paths


def test_posix_ytdlp_fix_is_single_line_executable_and_idempotent(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME")

    command = paths.render_ytdlp_fix_command()

    assert "\n" not in command
    shell = shutil.which("sh")
    if not shell:
        pytest.skip("POSIX sh is unavailable on this platform")
    subprocess.run([shell, "-c", command], check=True)
    subprocess.run([shell, "-c", command], check=True)

    config = tmp_path / ".config" / "yt-dlp" / "config"
    assert config.read_text(encoding="utf-8") == "--js-runtimes node\n"


def test_ytdlp_config_dir_matches_upstream_first_user_location(
    monkeypatch, tmp_path
):
    from yt_dlp.options import get_user_config_dirs

    config_home = tmp_path / "xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    expected = Path(next(get_user_config_dirs("yt-dlp")))

    assert paths.get_ytdlp_config_dir() == expected


def test_download_dir_env_override(tmp_path, monkeypatch):
    target = tmp_path / "agent-reach-output"
    monkeypatch.setenv("AGENT_REACH_DOWNLOAD_DIR", str(target))

    assert paths.get_agent_reach_download_dir() == target
    assert target.is_dir()


def test_download_dir_config_override(tmp_path, monkeypatch):
    target = tmp_path / "configured-output"
    monkeypatch.delenv("AGENT_REACH_DOWNLOAD_DIR", raising=False)
    config = Config(config_path=tmp_path / "config.yaml")
    config.set("download_dir", str(target))

    assert paths.get_agent_reach_download_dir(config) == target
    assert target.is_dir()


def test_download_dir_env_beats_config(tmp_path, monkeypatch):
    env_target = tmp_path / "env-output"
    config_target = tmp_path / "config-output"
    monkeypatch.setenv("AGENT_REACH_DOWNLOAD_DIR", str(env_target))
    config = Config(config_path=tmp_path / "config.yaml")
    config.set("download_dir", str(config_target))

    assert paths.get_agent_reach_download_dir(config) == env_target
    assert not config_target.exists()
