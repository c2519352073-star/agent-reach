# -*- coding: utf-8 -*-
"""Exa Search — check if mcporter + Exa MCP is available."""

import json
import shutil

from agent_reach.probe import probe_command

from .base import Channel
from .mcporter import McporterConfigError, inspect_mcporter_config


class ExaSearchChannel(Channel):
    name = "exa_search"
    description = "全网语义搜索"
    backends = ["Exa via mcporter"]
    tier = 0

    def can_handle(self, url: str) -> bool:
        return False  # Search-only channel

    def check(self, config=None):
        self.active_backend = None
        if not shutil.which("mcporter"):
            return "off", (
                "需要 mcporter + Exa MCP。安装：\n"
                "  npm install -g mcporter\n"
                "  mcporter config add exa https://mcp.exa.ai/mcp --scope home"
            )
        try:
            inspection = inspect_mcporter_config()
        except McporterConfigError as exc:
            return "error", f"mcporter 配置检查失败：{exc}"
        if "exa" in inspection.server_names:
            return "warn", (
                "Exa 已写入 mcporter 配置，但 Doctor 未启动远端服务做"
                "连通验证，不能仅凭配置宣称可用。若 `mcporter` 报 offline，"
                "先运行 `mcporter daemon restart` 后重试。"
            )
        if inspection.imports_unchecked:
            return "warn", (
                "mcporter 本地配置未发现 Exa；配置还启用了 editor imports，"
                "Doctor 为避免扩大凭据读取范围没有展开，当前未验证。"
            )
        return "off", (
            "mcporter 已装但 Exa 未配置。运行：\n"
            "  mcporter config add exa https://mcp.exa.ai/mcp --scope home"
        )

    def check_live(self, config=None):
        """Verify the configured Exa MCP server over the live mcporter daemon."""
        status, message = self.check(config)
        if status != "warn" or "未启动" not in message:
            return status, message

        result = probe_command(
            "mcporter",
            args=("list", "exa", "--json"),
            timeout=30,
            package="mcporter",
        )
        if result.status == "timeout":
            return "warn", result.hint
        if result.status in ("missing", "broken"):
            return "error", "mcporter 无法执行；请重新安装：npm install -g mcporter"
        if not result.ok:
            return "error", f"Exa MCP 连接检查失败：{result.output or result.status}"

        start = result.output.find("{")
        end = result.output.rfind("}")
        if start < 0 or end < start:
            return "error", "mcporter 没有返回可解析的 Exa 状态"
        try:
            payload = json.loads(result.output[start:end + 1])
        except json.JSONDecodeError as exc:
            return "error", f"mcporter 返回了无效 JSON：{exc}"
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            return "warn", "Exa MCP 已配置，但实时连接未就绪"

        self.active_backend = self.backends[0]
        tools = payload.get("tools")
        tool_count = len(tools) if isinstance(tools, list) else 0
        return "ok", f"Exa MCP 实时连接正常（{tool_count} 个工具）"
