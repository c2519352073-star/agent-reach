# -*- coding: utf-8 -*-
"""OpenCLI backend probing.

OpenCLI (github.com/jackwener/opencli) drives the user's real Chrome via a
browser-bridge extension + local daemon, reusing existing login sessions —
zero per-platform configuration, desktop-only (no headless).

Probing notes (verified live):
  - `opencli doctor` AUTO-STARTS the daemon — a side effect, so health
    checks must never use it.
  - Current OpenCLI startup also mutates ``~/.opencli`` before handling
    ``daemon status``. Only ``--version`` is a side-effect-free CLI fast path;
    live daemon state is read from its documented loopback ``/status`` API.
  - "Extension: disconnected" can mean a sleeping service worker, a disabled
    extension, or an extension that was never loaded. Disk files distinguish
    possible installation sources, but only a live daemon connection proves
    the browser actually loaded and enabled the extension.
"""

import glob
import json
import os
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass

from agent_reach.probe import probe_command

OPENCLI_PACKAGE = "@jackwener/opencli"
OPENCLI_EXTENSION_ID = "ildkmabpimmkaediidaifkhjpohdnifk"
OPENCLI_EXTENSION_URL = (
    f"https://chromewebstore.google.com/detail/opencli/{OPENCLI_EXTENSION_ID}"
)

# OpenCLIApp 0.1.35 injected this now-unsupported variable into every child.
# OpenCLI >=1.8.5 rejects it before even handling ``--version``.  Doctor is a
# read-only observer, so strip the stale app setting only from its child probes.
_UNSUPPORTED_APP_ENV = ("OPENCLI_DAEMON_PORT",)

#: Chromium-family profile roots that contain <Profile>/Extensions/<id>/
_CHROME_PROFILE_ROOTS = (
    "~/Library/Application Support/Google/Chrome",  # macOS Chrome
    "~/Library/Application Support/Chromium",       # macOS Chromium
    "~/Library/Application Support/Microsoft Edge",  # macOS Edge
    "~/.config/google-chrome",                      # Linux Chrome
    "~/.config/chromium",                           # Linux Chromium
    "~/.config/microsoft-edge",                     # Linux Edge
)

_OPENCLI_UNPACKED_EXTENSION = "~/.opencli/extension"
_OPENCLI_DAEMON_STATUS_URL = "http://127.0.0.1:19825/status"
_MAX_DAEMON_STATUS_BYTES = 64 * 1024


@dataclass(frozen=True)
class OpenCLIProfileInstallation:
    profile: str
    user_data_dir: str
    extension_path: str
    extension_id: str


def _chrome_profile_roots():
    roots = [os.path.expanduser(path) for path in _CHROME_PROFILE_ROOTS]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        roots.extend(
            [
                os.path.join(local_app_data, "Google", "Chrome", "User Data"),
                os.path.join(local_app_data, "Chromium", "User Data"),
                os.path.join(local_app_data, "Microsoft", "Edge", "User Data"),
            ]
        )
    return roots


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
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
            manifest = details.get("manifest")
            manifest = manifest if isinstance(manifest, dict) else {}
            name = str(manifest.get("name") or "")
            looks_like_opencli = (
                extension_id == OPENCLI_EXTENSION_ID
                or "opencli-extension" in extension_path.lower()
                or name.lower() == "opencli"
            )
            if looks_like_opencli:
                matches.append(
                    OpenCLIProfileInstallation(
                        profile=profile,
                        user_data_dir=os.path.dirname(profile_dir),
                        extension_path=extension_path,
                        extension_id=extension_id,
                    )
                )
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
    """Find store-installed and unpacked OpenCLI extensions by browser profile."""
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


def _fetch_daemon_status(timeout: int = 2):
    """Read OpenCLI's loopback status endpoint without starting the CLI."""
    request = urllib.request.Request(
        _OPENCLI_DAEMON_STATUS_URL,
        headers={"X-OpenCLI": "1"},
        method="GET",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=min(timeout, 2)) as response:
            raw = response.read(_MAX_DAEMON_STATUS_BYTES + 1)
    except Exception:
        return None
    if len(raw) > _MAX_DAEMON_STATUS_BYTES:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return None
    return payload


def _extension_installed_on_disk() -> bool:
    """True if store-installed OpenCLI files exist in a browser profile.

    This is disk evidence only: a user may have disabled or removed the
    extension while stale files remain, so callers must not treat it as proof
    that the extension is loaded, connected, or usable.
    """
    roots = [os.path.expanduser(p) for p in _CHROME_PROFILE_ROOTS]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:  # Windows
        roots.append(os.path.join(local_app_data, "Google", "Chrome", "User Data"))
        roots.append(os.path.join(local_app_data, "Microsoft", "Edge", "User Data"))
    for root in roots:
        if glob.glob(os.path.join(root, "*", "Extensions", OPENCLI_EXTENSION_ID)):
            return True
    return False


def _unpacked_extension_files_present() -> bool:
    """True when OpenCLI's unpacked extension source contains a manifest.

    ``~/.opencli/extension`` is downloaded source, not browser state.  Its
    existence never proves the user completed “Load unpacked” or left the
    extension enabled.
    """
    unpacked = os.path.expanduser(_OPENCLI_UNPACKED_EXTENSION)
    return os.path.isfile(os.path.join(unpacked, "manifest.json"))


@dataclass
class OpenCLIStatus:
    installed: bool = False
    broken: bool = False
    daemon_running: bool = False
    extension_connected: bool = False
    extension_installed: bool = False
    unpacked_extension_files: bool = False
    version: str = ""
    hint: str = ""

    @property
    def ready(self) -> bool:
        """True only when the backend is provably usable now.

        Only a live daemon connection proves that a browser loaded and enabled
        the extension. Disk files alone are deliberately not enough.
        """
        return self.installed and not self.broken and self.extension_connected


def _chrome_executable():
    candidates = []
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("PROGRAMFILES", "")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
        candidates.extend(
            [
                os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
            ]
        )
    elif os.uname().sysname == "Darwin":
        candidates.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
        )
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
    unpacked = [profile for profile in profiles if ".opencli" in profile.extension_path.lower()]
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


def opencli_status(timeout: int = 10) -> OpenCLIStatus:
    """Probe OpenCLI install + daemon/extension state without side effects."""
    version_probe = probe_command(
        "opencli",
        ["--version"],
        timeout=timeout,
        package=OPENCLI_PACKAGE,
        remove_env=_UNSUPPORTED_APP_ENV,
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

    daemon_status = _fetch_daemon_status(timeout)
    if daemon_status is not None:
        payload = daemon_status.get("data")
        payload = payload if isinstance(payload, dict) else daemon_status
        running = payload.get("running")
        st.daemon_running = bool(running) if running is not None else True
        profiles = payload.get("profiles") or []
        st.extension_connected = bool(payload.get("extensionConnected")) or any(
            isinstance(profile, dict) and profile.get("extensionConnected")
            for profile in profiles
        )

    if not st.extension_connected:
        st.extension_installed = _extension_installed_on_disk()
        st.unpacked_extension_files = _unpacked_extension_files_present()
        if st.extension_installed:
            st.hint = (
                "检测到 Chrome/Edge 的 OpenCLI 扩展文件，但扩展当前未连接；"
                "仅凭磁盘文件无法确认它已加载或启用。\n"
                "  打开浏览器扩展页确认 OpenCLI 已启用，再运行一个 opencli 命令验证"
            )
        elif st.unpacked_extension_files:
            st.hint = (
                "检测到 ~/.opencli/extension/ 源文件，但文件存在不代表已经在"
                " Chrome/Edge 中“加载已解压的扩展程序”。\n"
                "  请在浏览器扩展页加载并启用该目录，再运行一个 opencli 命令验证"
            )
        else:
            st.hint = (
                "OpenCLI 已安装，但未检测到已连接的浏览器扩展。\n"
                f"  1. 安装并启用扩展（Chrome/Edge）：{OPENCLI_EXTENSION_URL}\n"
                "  2. 保持浏览器打开，再运行一个 opencli 命令验证"
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
    if st.extension_installed:
        return "OpenCLI 已安装，检测到扩展文件但当前未连接（无法确认已加载）"
    if st.unpacked_extension_files:
        return "OpenCLI 已安装，检测到 unpacked 源文件但尚未确认浏览器已加载"
    if st.daemon_running:
        return "OpenCLI 已安装，等待 Chrome 扩展安装"
    return "OpenCLI 已安装（daemon 未运行，使用时自动启动；需 Chrome 扩展）"
