# -*- coding: utf-8 -*-
"""Tests for doctor module."""

import time

import pytest

import agent_reach.doctor as doctor
from agent_reach.config import Config


class _StubChannel:
    def __init__(self, name, description, tier, status, message, backends=None,
                 active_backend=None):
        self.name = name
        self.description = description
        self.tier = tier
        self._status = status
        self._message = message
        self.backends = backends or []
        self.active_backend = active_backend

    def check(self, config=None):
        return self._status, self._message


@pytest.fixture
def tmp_config(tmp_path):
    return Config(config_path=tmp_path / "config.yaml")


class TestDoctor:
    def test_check_all_collects_channel_results(self, tmp_config, monkeypatch):
        monkeypatch.setattr(
            doctor,
            "get_all_channels",
            lambda: [
                _StubChannel("web", "网页", 0, "ok", "可抓取网页", ["requests"],
                             active_backend="requests"),
                _StubChannel("github", "GitHub", 0, "warn", "gh 未安装", ["gh"]),
                _StubChannel("exa_search", "全网语义搜索", 1, "off", "mcporter 未配置", ["Exa"]),
            ],
        )

        results = doctor.check_all(tmp_config)

        assert results == {
            "web": {
                "status": "ok",
                "name": "网页",
                "message": "可抓取网页",
                "tier": 0,
                "backends": ["requests"],
                "active_backend": "requests",
            },
            "github": {
                "status": "warn",
                "name": "GitHub",
                "message": "gh 未安装",
                "tier": 0,
                "backends": ["gh"],
                "active_backend": None,
            },
            "exa_search": {
                "status": "off",
                "name": "全网语义搜索",
                "message": "mcporter 未配置",
                "tier": 1,
                "backends": ["Exa"],
                "active_backend": None,
            },
        }

    def test_format_report(self):
        report = doctor.format_report(
            {
                "web": {
                    "status": "ok",
                    "name": "网页",
                    "message": "可抓取网页",
                    "tier": 0,
                    "backends": ["requests"],
                },
                "exa_search": {
                    "status": "off",
                    "name": "全网语义搜索",
                    "message": "mcporter 未配置",
                    "tier": 1,
                    "backends": ["Exa"],
                },
                "xiaohongshu": {
                    "status": "warn",
                    "name": "小红书",
                    "message": "MCP 已配置，但健康检查超时",
                    "tier": 2,
                    "backends": ["mcporter"],
                },
            }
        )

        # Strip Rich markup tags for assertion (PR #170 added [bold], [yellow] etc.)
        import re
        plain = re.sub(r"\[[^\]]*\]", "", report)
        assert "Agent Reach" in plain
        assert "装好即用：" in plain
        assert "1/3 个渠道可用" in plain
        # Inactive optional channels should be summarized in one line
        assert "可选渠道可以解锁" in plain


def test_stale_active_backend_does_not_leak_into_errored_result(monkeypatch):
    """渠道单例上一轮的 active_backend 不得泄漏进本轮异常结果(Codex review 发现)。"""
    from agent_reach import doctor

    class _ExplodingChannel:
        name = "boom"
        description = "爆炸渠道"
        tier = 0
        backends = ["a", "b"]
        active_backend = "a"  # 上一轮成功的残留

        def check(self, config=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(doctor, "get_all_channels", lambda: [_ExplodingChannel()])
    results = doctor.check_all(config=None)
    assert results["boom"]["status"] == "error"
    assert results["boom"]["active_backend"] is None


def test_quick_mode_uses_fast_checks(monkeypatch):
    class _QuickChannel(_StubChannel):
        def __init__(self):
            super().__init__("quick", "快速", 0, "ok", "deep")
            self.quick_calls = 0

        def check(self, config=None):
            raise AssertionError("deep check must not run in quick mode")

        def check_quick(self, config=None):
            self.quick_calls += 1
            return "ok", "quick"

    channel = _QuickChannel()
    monkeypatch.setattr(doctor, "get_all_channels", lambda: [channel])
    results = doctor.check_all(config=None)
    assert results["quick"]["message"] == "quick"
    assert channel.quick_calls == 1


def test_check_all_runs_channels_in_parallel(monkeypatch):
    class _SlowChannel(_StubChannel):
        def check(self, config=None):
            time.sleep(0.2)
            return "ok", self.name

    channels = [
        _SlowChannel(f"slow{i}", f"慢{i}", 0, "ok", "")
        for i in range(4)
    ]
    monkeypatch.setattr(doctor, "get_all_channels", lambda: channels)
    started = time.monotonic()
    results = doctor.check_all(config=None, deep=True, max_workers=4)
    elapsed = time.monotonic() - started
    assert len(results) == 4
    assert elapsed < 0.55


def test_opencli_probe_is_shared_once(monkeypatch, tmp_config):
    class _OpenCLIChannel(_StubChannel):
        def __init__(self, name):
            super().__init__(name, name, 1, "ok", "ok", ["OpenCLI"])

        def check(self, config=None):
            assert getattr(config, "_doctor_opencli_status", None) == "shared"
            return "ok", "ok"

    calls = []

    def fake_status():
        calls.append(1)
        return "shared"

    monkeypatch.setattr("agent_reach.backends.opencli.opencli_status", fake_status)
    monkeypatch.setattr(
        doctor,
        "get_all_channels",
        lambda: [_OpenCLIChannel("twitter"), _OpenCLIChannel("reddit")],
    )
    results = doctor.check_all(tmp_config, deep=True, max_workers=2)
    assert set(results) == {"twitter", "reddit"}
    assert calls == [1]
