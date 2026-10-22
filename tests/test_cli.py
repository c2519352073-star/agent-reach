# -*- coding: utf-8 -*-
"""Tests for Agent Reach CLI."""

import shutil
import subprocess
from unittest.mock import patch

import pytest
import requests
import agent_reach.cli as cli
from agent_reach.cli import main


class TestCLI:
    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["agent-reach", "version"]):
                main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Agent Reach v" in captured.out

    def test_no_command_shows_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["agent-reach"]):
                main()
        assert exc_info.value.code == 0

    def test_doctor_runs(self, capsys):
        with patch("sys.argv", ["agent-reach", "doctor"]):
            main()
        captured = capsys.readouterr()
        assert "Agent Reach" in captured.out
        assert "✅" in captured.out

    def test_transcribe_command_prints_text(self, capsys):
        with patch("agent_reach.transcribe.transcribe", return_value="hello transcript"):
            with patch("sys.argv", ["agent-reach", "transcribe", "audio.mp3"]):
                main()
        captured = capsys.readouterr()
        assert "hello transcript" in captured.out

    def test_transcribe_command_writes_output_file(self, capsys, tmp_path):
        out_file = tmp_path / "t.txt"
        with patch("agent_reach.transcribe.transcribe", return_value="saved text"):
            with patch("sys.argv", ["agent-reach", "transcribe", "audio.mp3", "-o", str(out_file)]):
                main()
        assert out_file.read_text(encoding="utf-8").strip() == "saved text"
        assert "Transcript written" in capsys.readouterr().out

    def test_transcribe_relative_output_uses_download_dir(
        self, capsys, tmp_path, monkeypatch
    ):
        download_root = tmp_path / "downloads"
        monkeypatch.setenv("AGENT_REACH_DOWNLOAD_DIR", str(download_root))
        with patch("agent_reach.transcribe.transcribe", return_value="saved text"):
            with patch("sys.argv", ["agent-reach", "transcribe", "audio.mp3", "-o", "t.txt"]):
                main()
        out_file = download_root / "t.txt"
        assert out_file.read_text(encoding="utf-8").strip() == "saved text"
        assert str(out_file) in capsys.readouterr().out

    def test_configure_download_dir(self, capsys, tmp_path, monkeypatch):
        from agent_reach.config import Config

        config_dir = tmp_path / "config"
        config_file = config_dir / "config.yaml"
        target = tmp_path / "downloads" / "技能下载文件"
        monkeypatch.setattr(Config, "CONFIG_DIR", config_dir)
        monkeypatch.setattr(Config, "CONFIG_FILE", config_file)

        with patch(
            "sys.argv",
            ["agent-reach", "configure", "download-dir", str(target)],
        ):
            main()

        assert target.is_dir()
        assert Config().get("download_dir") == str(target)
        assert "下载目录已配置" in capsys.readouterr().out

    def test_twitter_search_uses_opencli(self, capsys):
        completed = subprocess.CompletedProcess(
            ["opencli"], 0, "results\n", ""
        )
        with patch("shutil.which", return_value="/usr/bin/opencli"), patch(
            "subprocess.run", return_value=completed
        ) as run:
            with patch(
                "sys.argv",
                ["agent-reach", "twitter-search", "OpenAI", "-f", "json"],
            ):
                main()

        assert run.call_args.args[0] == [
            "/usr/bin/opencli",
            "twitter",
            "search",
            "OpenAI",
            "-f",
            "json",
            "--window",
            "foreground",
            "--site-session",
            "persistent",
        ]
        assert "twitter" not in capsys.readouterr().out.lower()

    def test_twitter_search_uses_dom_when_adapter_fetch_fails(self, capsys):
        import json

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            action = cmd[2]
            if action == "search":
                return subprocess.CompletedProcess(
                    cmd, 1, "", "TypeError: Failed to fetch"
                )
            if action == "extract":
                payload = {"ok": True, "data": {"content": "OpenAI result"}}
                return subprocess.CompletedProcess(
                    cmd, 0, json.dumps(payload), ""
                )
            return subprocess.CompletedProcess(cmd, 0, "{}", "")

        with patch("shutil.which", return_value="/usr/bin/opencli"), patch(
            "subprocess.run", side_effect=fake_run
        ):
            with patch(
                "sys.argv",
                ["agent-reach", "twitter-search", "OpenAI", "-f", "json"],
            ):
                main()

        payload = json.loads(capsys.readouterr().out)
        assert payload["source"] == "opencli-browser-dom"
        assert payload["content"] == "OpenAI result"
        assert calls[-1][2] == "close"

    def test_youtube_download_dispatches_wrapper(self, capsys, tmp_path):
        with patch(
            "agent_reach.youtube_download.download_youtube",
            return_value=tmp_path,
        ), patch(
            "sys.argv",
            ["agent-reach", "youtube-download", "https://youtu.be/test", "--simulate"],
        ):
            main()

        out = capsys.readouterr().out
        assert "模拟完成" in out
        assert str(tmp_path) in out

    def test_bili_wrapper_forces_utf8(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(
            shutil, "which",
            lambda name: "/usr/bin/bili" if name == "bili" else None,
        )
        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(SystemExit) as exc_info:
            with patch(
                "sys.argv",
                ["agent-reach", "bili", "search", "OpenAI", "--json"],
            ):
                main()

        assert exc_info.value.code == 0
        assert calls[0][0] == [
            "/usr/bin/bili",
            "search",
            "OpenAI",
            "--json",
        ]
        assert calls[0][1]["env"]["PYTHONUTF8"] == "1"
        assert calls[0][1]["env"]["PYTHONIOENCODING"] == "utf-8"

    def test_parse_twitter_cookie_input_separate_values(self):
        auth_token, ct0 = cli._parse_twitter_cookie_input("token123 ct0abc")
        assert auth_token == "token123"
        assert ct0 == "ct0abc"

    def test_parse_twitter_cookie_input_cookie_header(self):
        auth_token, ct0 = cli._parse_twitter_cookie_input(
            "auth_token=token123; ct0=ct0abc; other=value"
        )
        assert auth_token == "token123"
        assert ct0 == "ct0abc"

    def test_install_rdt_cli_prefers_github_source(self, monkeypatch, capsys):
        state = {"rdt_installed": False}
        commands = []

        def fake_which(name):
            if name == "rdt":
                return "/usr/local/bin/rdt" if state["rdt_installed"] else None
            if name == "pipx":
                return "/usr/local/bin/pipx"
            return None

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            state["rdt_installed"] = True
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(shutil, "which", fake_which)
        monkeypatch.setattr(subprocess, "run", fake_run)

        cli._install_rdt_cli()

        out = capsys.readouterr().out
        assert commands == [["pipx", "install", cli._RDT_GIT_SOURCE]]
        assert "✅ rdt-cli installed" in out

    def test_install_reddit_deps_routes_by_environment(self, monkeypatch):
        """桌面 → OpenCLI;服务器 → rdt-cli(钉 git 源)。"""
        calls = []
        monkeypatch.setattr(cli, "_install_opencli_deps", lambda: calls.append("opencli"))
        monkeypatch.setattr(cli, "_install_rdt_cli", lambda: calls.append("rdt"))
        monkeypatch.setattr(shutil, "which", lambda _: None)

        monkeypatch.setattr(cli, "_detect_environment", lambda: "local")
        cli._install_reddit_deps()
        assert calls == ["opencli"]

        calls.clear()
        monkeypatch.setattr(cli, "_detect_environment", lambda: "server")
        cli._install_reddit_deps()
        assert calls == ["rdt"]


class TestCheckUpdateRetry:
    def test_auto_headers_use_configured_github_token(self, monkeypatch):
        class FakeConfig:
            def get(self, key):
                return "ghp_test" if key == "github_token" else None

        monkeypatch.setattr("agent_reach.config.Config", FakeConfig)
        headers = cli._github_auth_headers()
        assert headers["Authorization"] == "Bearer ghp_test"
        assert headers["Accept"] == "application/vnd.github+json"

    def test_retry_uses_auto_github_headers(self, monkeypatch):
        captured = {}

        class R:
            status_code = 200
            headers = {}

        def fake_get(url, timeout, headers):
            captured.update({"url": url, "timeout": timeout, "headers": headers})
            return R()

        monkeypatch.setattr(
            cli,
            "_github_auth_headers",
            lambda: {"Authorization": "Bearer ghp_test"},
        )
        with patch("requests.get", side_effect=fake_get):
            resp, err, attempts = cli._github_get_with_retry(
                "https://api.github.com/test",
                timeout=1,
                retries=1,
            )

        assert err is None
        assert resp.status_code == 200
        assert attempts == 1
        assert captured["headers"]["Authorization"] == "Bearer ghp_test"

    def test_retry_timeout_classification(self):
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)

        with patch("requests.get", side_effect=requests.exceptions.Timeout("timed out")):
            resp, err, attempts = cli._github_get_with_retry(
                "https://api.github.com/test",
                timeout=1,
                retries=3,
                sleeper=fake_sleep,
            )

        assert resp is None
        assert err == "timeout"
        assert attempts == 3
        assert sleeps == [1, 2]

    def test_retry_dns_classification(self):
        error = requests.exceptions.ConnectionError("getaddrinfo failed for api.github.com")
        with patch("requests.get", side_effect=error):
            resp, err, attempts = cli._github_get_with_retry(
                "https://api.github.com/test",
                retries=1,
                sleeper=lambda _x: None,
            )
        assert resp is None
        assert err == "dns"
        assert attempts == 1

    def test_retry_rate_limit_then_success(self):
        sleeps = []

        class R:
            def __init__(self, code, payload=None, headers=None):
                self.status_code = code
                self._payload = payload or {}
                self.headers = headers or {}

            def json(self):
                return self._payload

        sequence = [
            R(429, headers={"Retry-After": "3"}),
            R(200, payload={"tag_name": "v1.5.0"}),
        ]

        with patch("requests.get", side_effect=sequence):
            resp, err, attempts = cli._github_get_with_retry(
                "https://api.github.com/test",
                retries=3,
                sleeper=lambda s: sleeps.append(s),
            )

        assert err is None
        assert resp is not None
        assert resp.status_code == 200
        assert attempts == 2
        assert sleeps == [3.0]

    def test_classify_rate_limit_from_403(self):
        class R:
            status_code = 403
            headers = {"X-RateLimit-Remaining": "0"}

            @staticmethod
            def json():
                return {"message": "API rate limit exceeded"}

        assert cli._classify_github_response_error(R()) == "rate_limit"

    def test_check_update_reports_classified_error(self, capsys):
        with patch("agent_reach.cli._github_get_with_retry", return_value=(None, "timeout", 3)):
            result = cli._cmd_check_update()

        captured = capsys.readouterr()
        assert result == "error"
        assert "网络超时" in captured.out
        assert "已重试 3 次" in captured.out


class TestVersionCompare:
    def test_newer_remote_triggers_update(self):
        assert cli._is_newer_version("1.5.0", "1.4.2") is True

    def test_equal_versions_no_update(self):
        assert cli._is_newer_version("1.5.0", "1.5.0") is False

    def test_local_ahead_of_release_no_downgrade_prompt(self):
        """发版窗口期本地装了 main(更新)时,不能提示"有更新"诱导降级。"""
        assert cli._is_newer_version("1.4.2", "1.5.0") is False

    def test_unparseable_falls_back_to_inequality(self):
        assert cli._is_newer_version("2026.06-beta", "1.5.0") is True
        assert cli._is_newer_version("1.5.0", "1.5.0-dev") is True


class TestWatchVersionCompare:
    def test_watch_does_not_prompt_downgrade(self, monkeypatch, capsys):
        """watch 与 check-update 同语义:本地领先远端 release 时不提示更新。"""
        class R:
            status_code = 200
            headers = {}

            @staticmethod
            def json():
                return {"tag_name": "v1.4.2", "body": ""}

        monkeypatch.setattr(cli, "_github_get_with_retry", lambda *a, **k: (R(), None, 1))
        monkeypatch.setattr(
            "agent_reach.doctor.check_all",
            lambda config: {"web": {"status": "ok", "name": "任意网页", "message": "ok",
                            "tier": 0, "backends": ["Jina Reader"], "active_backend": "Jina Reader"}},
        )
        cli._cmd_watch()
        out = capsys.readouterr().out
        assert "新版本可用" not in out
        assert "全部正常" in out
