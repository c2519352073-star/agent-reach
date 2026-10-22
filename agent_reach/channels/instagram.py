# -*- coding: utf-8 -*-
"""Instagram — OpenCLI backend using the user's logged-in Chrome session."""

import json

from agent_reach.probe import probe_command

from ._opencli_site import OpenCLISiteChannel


class InstagramChannel(OpenCLISiteChannel):
    name = "instagram"
    description = "Instagram 用户、主页和指定用户帖子"
    site = "instagram"
    domains = ("instagram.com", "instagr.am")
    usage = "opencli instagram search/profile/user/explore -f yaml"
    login_hint = "instagram.com"

    def check_live(self, config=None):
        """Verify Instagram login through OpenCLI without reading cookie values."""
        status, message = super().check(config)
        if "未实时验证" not in message:
            return status, message

        result = probe_command(
            "opencli",
            args=(
                "auth",
                "status",
                "--site",
                "instagram",
                "--full",
                "-f",
                "json",
            ),
            timeout=45,
            package="@jackwener/opencli",
        )
        if result.status == "timeout":
            return "warn", result.hint
        if result.status in ("missing", "broken"):
            return "error", "OpenCLI 无法执行；请检查全局安装和 Chrome 扩展"
        if not result.ok:
            return "error", f"Instagram 登录态检查失败：{result.output or result.status}"

        start = result.output.find("{")
        end = result.output.rfind("}")
        if start < 0 or end < start:
            return "error", "OpenCLI 没有返回可解析的 Instagram 登录状态"
        try:
            payload = json.loads(result.output[start:end + 1])
        except json.JSONDecodeError as exc:
            return "error", f"OpenCLI 返回了无效 JSON：{exc}"

        rows = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            rows = [rows] if isinstance(rows, dict) else []
        row = next((item for item in rows if isinstance(item, dict)), {})
        if row.get("logged_in") is not True:
            return "warn", "OpenCLI 已连接，但 Instagram 尚未登录"

        self.active_backend = "OpenCLI"
        identity = str(row.get("identity") or "").strip()
        suffix = f"：@{identity}" if identity else ""
        return "ok", f"Instagram 登录态已验证{suffix}"
