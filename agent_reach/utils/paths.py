"""Cross-platform path and remediation helpers for yt-dlp."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def get_ytdlp_config_dir() -> Path:
    """Return the recommended yt-dlp user config directory for this OS."""

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "yt-dlp"
        return Path.home() / "AppData" / "Roaming" / "yt-dlp"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "yt-dlp"
    return Path.home() / ".config" / "yt-dlp"


def get_ytdlp_config_path() -> Path:
    """Return the yt-dlp user config file path for this OS."""

    return get_ytdlp_config_dir() / "config"


def get_agent_reach_download_dir(config=None) -> Path:
    """Return the persistent output/download directory used by Agent Reach.

    Priority: AGENT_REACH_DOWNLOAD_DIR, config download_dir, then E: on
    Windows when available, otherwise ~/Downloads/agent-reach.
    """

    override = os.environ.get("AGENT_REACH_DOWNLOAD_DIR")
    if not override and config is not None:
        override = getattr(config, "data", {}).get("download_dir")

    if override:
        root = Path(os.path.expandvars(os.path.expanduser(str(override))))
    elif sys.platform == "win32" and Path("E:/").is_dir():
        root = Path("E:/agent-reach/技能下载文件")
    else:
        root = Path.home() / "Downloads" / "agent-reach"

    root.mkdir(parents=True, exist_ok=True)
    return root


def render_ytdlp_fix_command() -> str:
    """Return an OS-appropriate command to enable Node.js as yt-dlp JS runtime."""

    config_path = get_ytdlp_config_path()
    if sys.platform == "win32":
        return (
            f"$cfg = '{config_path}'\n"
            "New-Item -ItemType Directory -Force -Path (Split-Path $cfg) | Out-Null\n"
            "if (-not (Test-Path $cfg) -or -not (Select-String -Path $cfg -Pattern '--js-runtimes' -Quiet)) {\n"
            "  Add-Content -Path $cfg -Value '--js-runtimes node'\n"
            "}"
        )
    return (
        f"mkdir -p '{config_path.parent}' && "
        f"grep -qxF -- '--js-runtimes node' '{config_path}' 2>/dev/null || "
        f"printf '%s\n' '--js-runtimes node' >> '{config_path}'"
    )
