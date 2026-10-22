# -*- coding: utf-8 -*-
"""Safely merge upstream Agent Reach changes into the local editable checkout."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class UpdateError(RuntimeError):
    """Raised when a safe local update cannot continue."""


@dataclass(frozen=True)
class UpdateStatus:
    root: Path
    branch: str
    head: str
    upstream: str
    behind: int
    ahead: int

    @property
    def update_available(self) -> bool:
        return self.behind > 0


def _run(args: Sequence[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise UpdateError(f"{' '.join(args)} failed: {detail}")
    return result


def _git(root: Path, *args: str, check: bool = True) -> str:
    return _run(["git", *args], cwd=root, check=check).stdout.strip()


def _repo_root(start: Path | None = None) -> Path:
    source_root = Path(__file__).resolve().parent.parent
    result = _run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start or source_root,
        check=False,
    )
    if result.returncode != 0:
        raise UpdateError("Current directory is not inside the Agent Reach Git checkout.")
    return Path(result.stdout.strip()).resolve()


def _ensure_clean(root: Path) -> None:
    status = _git(root, "status", "--porcelain")
    if status:
        raise UpdateError(f"Working tree is not clean:\n{status}")


def _branch(root: Path) -> str:
    branch = _git(root, "branch", "--show-current")
    if not branch:
        raise UpdateError("Detached HEAD is not supported; switch to a local branch first.")
    return branch


def _patch_script(root: Path) -> Path:
    script = root / "patches" / "opencli" / "reapply.py"
    if not script.exists():
        raise UpdateError(f"OpenCLI patch tool not found: {script}")
    return script


def _check_opencli_patches(root: Path) -> None:
    script = _patch_script(root)
    result = _run([sys.executable, str(script), "--check"], cwd=root)
    print(result.stdout.strip())


def _fetch_status(root: Path) -> UpdateStatus:
    _git(root, "fetch", "origin", "main:refs/remotes/origin/main")
    return UpdateStatus(
        root=root,
        branch=_branch(root),
        head=_git(root, "rev-parse", "--short", "HEAD"),
        upstream=_git(root, "rev-parse", "--short", "origin/main"),
        behind=int(_git(root, "rev-list", "--count", "HEAD..origin/main")),
        ahead=int(_git(root, "rev-list", "--count", "origin/main..HEAD")),
    )


def _print_status(status: UpdateStatus) -> None:
    print(f"Repository: {status.root}")
    print(f"Branch: {status.branch}")
    print(f"Local HEAD: {status.head}")
    print(f"origin/main: {status.upstream}")
    print(f"Ahead: {status.ahead}, behind: {status.behind}")


def _verify_editable_install(root: Path) -> None:
    probe = (
        "import pathlib, agent_reach; "
        "print(pathlib.Path(agent_reach.__file__).resolve().parent.parent)"
    )
    result = _run([sys.executable, "-c", probe], cwd=Path.home())
    active = Path(result.stdout.strip()).resolve()
    if not active.samefile(root):
        raise UpdateError(
            f"Active agent_reach package is {active}, expected editable checkout {root}."
        )


def update_local(*, check_only: bool = False) -> int:
    """Check or apply a safe local update without replacing the editable checkout."""
    root = _repo_root()
    _ensure_clean(root)
    _check_opencli_patches(root)
    status = _fetch_status(root)
    _print_status(status)

    if not status.update_available:
        print("Agent Reach is already current.")
        return 0
    if check_only:
        print("Update available. Run: agent-reach update-local")
        return 0

    print("Merging origin/main...")
    merge = _run(["git", "merge", "--no-edit", "origin/main"], cwd=root, check=False)
    if merge.returncode != 0:
        _run(["git", "merge", "--abort"], cwd=root, check=False)
        detail = (merge.stderr or merge.stdout or "").strip()
        raise UpdateError(f"Merge conflict; update aborted and local branch restored.\n{detail}")

    _check_opencli_patches(root)
    print("Running tests...")
    _run([sys.executable, "-m", "pytest", "-q"], cwd=root)
    print("Reinstalling editable package...")
    _run([sys.executable, "-m", "pip", "install", "-e", str(root)], cwd=root)
    print("Reapplying OpenCLI patches...")
    _run([sys.executable, str(_patch_script(root))], cwd=root)
    print("Syncing Agent Reach skill files...")
    _run(
        [sys.executable, "-m", "agent_reach.cli", "skill", "--install"],
        cwd=root,
    )
    _verify_editable_install(root)
    print("Safe update complete.")
    return 0
