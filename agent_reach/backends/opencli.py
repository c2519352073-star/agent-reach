# -*- coding: utf-8 -*-
"""OpenCLI backend probing.

OpenCLI (github.com/jackwener/opencli) drives the user's real Chrome via a
browser-bridge extension + local daemon, reusing existing login sessions —
zero per-platform configuration, desktop-only (no headless).

Probing notes (verified live):
  - `opencli doctor` AUTO-STARTS the daemon — a side effect, so health
    checks must use `opencli daemon status` (pure query) instead.
  - OpenCLI 2.x emits JSON result envelopes and meaningful exit codes;
    1.x often exited 0 and printed human-readable status text.
  - "Extension: disconnected" does NOT mean unusable: the extension's
    service worker sleeps and any real opencli command wakes it up
    (verified: status flips disconnected→connected after one call).
    Since daemon status can't tell "sleeping" from "never installed",
    we check Chrome's Extensions directory on disk to disambiguate.
"""

import glob
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass

from agent_reach.probe import probe_command

OPENCLI_PACKAGE = "@jackwener/opencli"
OPENCLI_EXTENSION_ID = "ildkmabpimmkaediidaifkhjpohdnifk"
OPENCLI_EXTENSION_URL = (
    f"https://chromewebstore.google.com/detail/opencli/{OPENCLI_EXTENSION_ID}"
)

#: Chrome-family profile roots that contain <Profile>/Extensions/<id>/
_CHROME_PROFILE_ROOTS = (
    "~/Library/Application Support/Google/Chrome",  # macOS Chrome
    "~/Library/Application Support/Chromium",       # macOS Chromium
    "~/.config/google-chrome",                      # Linux Chrome
    "~/.config/chromium",                           # Linux Chromium
)


@dataclass
class OpenCLIProfileInstallation:
    profile: str
    user_data_dir: str
    extension_path: str
    extension_id: str


def _chrome_profile_roots():
    roots = [os.path.expanduser(p) for p in _CHROME_PROFILE_ROOTS]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:  # Windows
        roots.append(os.path.join(local_app_data, "Google", "Chrome", "User Data"))
        roots.append(os.path.join(local_app_data, "Chromium", "User Data"))
    return roots


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _profile_has_opencli(profile_dir: str):
    profile = os.path.basename(profile_dir)
    store_path = os.path.join(profile_dir, "Extensions", OPENCLI_EXTENSION_ID)
    if os.path.isdir(store_path):
        return OpenCLIProfileInstallation(
            profile=profile,
            user_data_dir=os.path.dirname(profile_dir),
            extension_path=store_path,
            extension_id=OPENCLI_EXTENSION_ID,
        )

    matches = []
    for filename in ("Secure Preferences", "Preferences"):
        data = _read_json(os.path.join(profile_dir, filename))
        settings = ((data or {}).get("extensions") or {}).get("settings") or {}
        for extension_id, details in settings.items():
            if not isinstance(details, dict):
                continue
            extension_path = str(details.get("path") or "")
            manifest = details.get("manifest") if isinstance(details.get("manifest"), dict) else {}
            name = str(manifest.get("name") or "")
            looks_like_opencli = (
                extension_id == OPENCLI_EXTENSION_ID
                or "opencli-extension" in extension_path.lower()
                or name.lower() == "opencli"
            )
            if looks_like_opencli:
                matches.append(OpenCLIProfileInstallation(
                    profile=profile,
                    user_data_dir=os.path.dirname(profile_dir),
                    extension_path=extension_path,
                    extension_id=extension_id,
                ))
    if not matches:
        return None
    return max(
        matches,
        key=lambda item: (
            os.path.exists(item.extension_path),
            ".opencli" in item.extension_path.lower(),
            "opencli-extension" in item.extension_path.lower(),
        ),
    )


def find_opencli_profiles() -> list[OpenCLIProfileInstallation]:
    """Find store-installed and unpacked OpenCLI extensions by Chrome profile."""
    found = {}
    for root in _chrome_profile_roots():
        if not os.path.isdir(root):
            continue
        for profile_dir in glob.glob(os.path.join(root, "*")):
            if not os.path.isdir(profile_dir):
                continue
            if not (
                os.path.exists(os.path.join(profile_dir, "Preferences"))
                or os.path.exists(os.path.join(profile_dir, "Secure Preferences"))
            ):
                continue
            installation = _profile_has_opencli(profile_dir)
            if installation is None:
                continue
            key = (installation.user_data_dir.lower(), installation.profile.lower())
            current = found.get(key)
            if current is None or (
                os.path.exists(installation.extension_path)
                and not os.path.exists(current.extension_path)
            ):
                found[key] = installation
    return list(found.values())


def _extension_installed_on_disk() -> bool:
    """True if OpenCLI is installed as a store or unpacked Chrome extension."""
    return bool(find_opencli_profiles())


def _chrome_executable():
    candidates = []
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("PROGRAMFILES", "")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
        candidates.extend([
            os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(program_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
        ])
    elif os.uname().sysname == "Darwin":
        candidates.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ])
    else:
        candidates.extend(["google-chrome", "chromium", "chromium-browser"])

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    for command in ("chrome", "google-chrome", "chromium", "chromium-browser"):
        resolved = shutil.which(command)
        if resolved:
            return resolved
    return None


def _preferred_profile(profiles):
    requested = os.environ.get("OPENCLI_CHROME_PROFILE", "").strip().lower()
    if requested:
        for profile in profiles:
            if profile.profile.lower() == requested:
                return profile
    unpacked = [p for p in profiles if ".opencli" in p.extension_path.lower()]
    return (unpacked or profiles)[0]


def _launch_chrome_profile(installation: OpenCLIProfileInstallation) -> bool:
    executable = _chrome_executable()
    if not executable:
        return False
    args = [
        executable,
        f"--profile-directory={installation.profile}",
        "--no-first-run",
        "--start-minimized",
        "about:blank",
    ]
    try:
        subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        return True
    except OSError:
        return False


def ensure_opencli_ready(timeout: int = 15) -> OpenCLIStatus:
    """Wake the matching Chrome profile and wait for the extension handshake."""
    status = opencli_status()
    if status.extension_connected:
        return status
    if not status.installed or status.broken:
        return status

    profiles = find_opencli_profiles()
    if not profiles:
        status.hint = (
            "OpenCLI 扩展未安装。\n"
            f"  安装：{OPENCLI_EXTENSION_URL}\n"
            "  或加载 opencli-extension-v<version> 解压目录"
        )
        return status

    installation = _preferred_profile(profiles)
    if not _launch_chrome_profile(installation):
        status.hint = "无法定位或启动 Chrome。请手动打开安装了 OpenCLI 扩展的浏览器 Profile。"
        return status

    deadline = time.monotonic() + max(1, timeout)
    while time.monotonic() < deadline:
        time.sleep(1)
        status = opencli_status()
        if status.extension_connected:
            return status

    status.hint = (
        f"已尝试启动 Chrome {installation.profile}，但 OpenCLI 扩展未在 {timeout:g}s 内连接。\n"
        "  检查 chrome://extensions 中 OpenCLI 是否已启用。"
    )
    return status


def opencli_status_for(config=None, timeout: int = 10) -> OpenCLIStatus:
    """Return the doctor-shared OpenCLI result when available."""
    cached = getattr(config, "_doctor_opencli_status", None) if config is not None else None
    return cached if cached is not None else opencli_status(timeout=timeout)


@dataclass
class OpenCLIStatus:
    installed: bool = False
    broken: bool = False
    daemon_running: bool = False
    extension_connected: bool = False
    extension_installed: bool = False
    version: str = ""
    hint: str = ""

    @property
    def ready(self) -> bool:
        """Usable now or on first call.

        A live connection counts, and so does an installed-but-sleeping
        extension: its service worker wakes on the first real command.
        """
        return self.installed and not self.broken and (
            self.extension_connected or self.extension_installed
        )


def opencli_status(timeout: int = 10) -> OpenCLIStatus:
    """Probe OpenCLI install + daemon/extension state without side effects."""
    version_probe = probe_command(
        "opencli", ["--version"], timeout=timeout, package=OPENCLI_PACKAGE
    )
    if version_probe.status == "missing":
        return OpenCLIStatus(installed=False)
    if not version_probe.ok:
        return OpenCLIStatus(
            installed=True,
            broken=True,
            hint=(
                "opencli 命令存在但无法执行（node 环境损坏），重装：\n"
                f"  npm install -g {OPENCLI_PACKAGE}"
            ),
        )

    st = OpenCLIStatus(installed=True, version=version_probe.output.strip())

    daemon_probe = probe_command(
        "opencli", ["daemon", "status"], timeout=timeout, package=OPENCLI_PACKAGE
    )
    output = daemon_probe.output if daemon_probe.ok else ""
    try:
        daemon_data = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        daemon_data = None
    if isinstance(daemon_data, dict):
        data = daemon_data.get("data")
        if daemon_data.get("ok") is True and isinstance(data, dict):
            st.daemon_running = bool(data.get("running"))
            profiles = data.get("profiles") or []
            st.extension_connected = bool(data.get("extensionConnected")) or any(
                isinstance(profile, dict) and profile.get("extensionConnected")
                for profile in profiles
            )
    else:
        # Legacy OpenCLI releases print human-readable status lines.
        #   Daemon: running (PID 37389) / Daemon: not running
        #   Extension: connected / Extension: disconnected
        for line in output.splitlines():
            line = line.strip().lower()
            if line.startswith("daemon:"):
                st.daemon_running = "not running" not in line and "running" in line
            elif line.startswith("extension:"):
                st.extension_connected = "disconnected" not in line and "connected" in line

    if not st.extension_connected:
        st.extension_installed = _extension_installed_on_disk()
        if not st.extension_installed:
            st.hint = (
                "OpenCLI 已安装，但 Chrome 扩展未安装。\n"
                f"  1. 安装扩展（需手动点一次）：{OPENCLI_EXTENSION_URL}\n"
                "  2. 保持 Chrome 打开，运行 `opencli doctor` 验证"
            )
    return st


def opencli_summary(st: OpenCLIStatus) -> str:
    """One-line state description for channel messages / install output."""
    if not st.installed:
        return "OpenCLI 未安装"
    if st.broken:
        return "OpenCLI 无法执行（node 环境损坏）"
    if st.extension_connected:
        return f"OpenCLI 可用（浏览器登录态，v{st.version}）"
    if st.ready:
        return "OpenCLI 可用（扩展睡眠中，调用时自动唤醒）"
    if st.daemon_running:
        return "OpenCLI 已安装，等待 Chrome 扩展安装"
    return "OpenCLI 已安装（daemon 未运行，使用时自动启动；需 Chrome 扩展）"
