# -*- coding: utf-8 -*-
"""Download YouTube videos through the verified Cookie + EJS + PO Token path."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from agent_reach.config import Config
from agent_reach.utils.paths import get_agent_reach_download_dir


class YouTubeDownloadError(RuntimeError):
    """Raised when a YouTube download cannot start or finish."""


def chrome_cookie_db(cookie_source: str) -> Optional[Path]:
    """Return the Chrome Cookies database represented by a yt-dlp source."""
    if not cookie_source.startswith("chrome"):
        return None
    profile = cookie_source.split(":", 1)[1] if ":" in cookie_source else "Default"
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None
    return (
        Path(local_appdata)
        / "Google"
        / "Chrome"
        / "User Data"
        / (profile or "Default")
        / "Network"
        / "Cookies"
    )


def ensure_cookie_access(cookie_source: str) -> None:
    """Fail early when Chrome has locked the selected Cookie database."""
    path = chrome_cookie_db(cookie_source)
    if path is None or not path.exists():
        return
    try:
        with path.open("rb") as fh:
            fh.read(1)
    except PermissionError as exc:
        raise YouTubeDownloadError(
            f"Chrome Cookie 数据库被占用：{path}\n"
            "请完全退出该 Chrome Profile，或改用不常驻的专用 Profile，例如 "
            '--cookies-from-browser "chrome:Profile 2"。'
        ) from exc
    except OSError as exc:
        raise YouTubeDownloadError(f"无法读取 Chrome Cookie 数据库：{path}\n{exc}") from exc


def build_command(
    url: str,
    *,
    output_dir: Path,
    quality: int,
    cookie_source: Optional[str],
    no_cookies: bool = False,
    simulate: bool = False,
) -> List[str]:
    """Build a deterministic yt-dlp command without executing it."""
    if quality < 144 or quality > 4320:
        raise YouTubeDownloadError("quality 必须在 144 到 4320 之间")

    cache_dir = output_dir / ".cache" / "yt-dlp"
    output_template = output_dir / "%(title)s [%(id)s].%(ext)s"
    fmt = (
        f"bv*[ext=mp4][height<={quality}]+ba[ext=m4a]/"
        f"b[ext=mp4][height<={quality}]"
    )
    cmd = [
        "yt-dlp",
        "--newline",
        "--progress",
        "--no-playlist",
        "--continue",
        "--retries",
        "5",
        "--fragment-retries",
        "5",
        "--cache-dir",
        str(cache_dir),
        "--format",
        fmt,
        "--merge-output-format",
        "mp4",
        "--remote-components",
        "ejs:github",
        "--extractor-args",
        "youtube:player-client=mweb",
        "--js-runtimes",
        "node",
    ]
    if not no_cookies:
        if not cookie_source:
            raise YouTubeDownloadError("缺少浏览器 Cookie 来源")
        cmd.extend(["--cookies-from-browser", cookie_source])
    if simulate:
        cmd.append("--simulate")
    cmd.extend(["-o", str(output_template), url])
    return cmd


def download_youtube(
    url: str,
    *,
    quality: int = 720,
    output_dir: Optional[Path] = None,
    cookie_source: Optional[str] = None,
    no_cookies: bool = False,
    simulate: bool = False,
    config: Optional[Config] = None,
) -> Path:
    """Download one YouTube video into the Agent Reach E-drive directory."""
    cfg = config or Config()
    root = Path(output_dir).expanduser() if output_dir else get_agent_reach_download_dir(cfg)
    root.mkdir(parents=True, exist_ok=True)
    (root / ".cache" / "yt-dlp").mkdir(parents=True, exist_ok=True)

    resolved = {}
    for binary in ("yt-dlp", "node"):
        resolved[binary] = shutil.which(binary)
        if not resolved[binary]:
            raise YouTubeDownloadError(f"{binary} 未安装或不可执行")
    if not simulate and not shutil.which("ffmpeg"):
        raise YouTubeDownloadError("ffmpeg 未安装或不可执行")

    if not no_cookies:
        cookie_source = (
            cookie_source
            or cfg.get("youtube_cookies_from")
            or "chrome:Profile 2"
        )
        ensure_cookie_access(cookie_source)

    cmd = build_command(
        url,
        output_dir=root,
        quality=quality,
        cookie_source=cookie_source,
        no_cookies=no_cookies,
        simulate=simulate,
    )
    cmd[0] = resolved["yt-dlp"]
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise YouTubeDownloadError(f"yt-dlp 退出码 {proc.returncode}")
    return root
