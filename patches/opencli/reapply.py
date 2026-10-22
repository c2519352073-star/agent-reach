#!/usr/bin/env python3
"""Reapply Agent Reach's OpenCLI compatibility patches after an upgrade."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

EXPECTED_VERSION = "2.0.2"
PATCH_DIR = Path(__file__).resolve().parent / f"v{EXPECTED_VERSION}"


def run(args, *, cwd=None, check=True):
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"{' '.join(args)} failed: {detail}")
    return result


def package_root() -> Path:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm not found")
    root = Path(run([npm, "root", "-g"]).stdout.strip())
    return root / "@jackwener" / "opencli"


def verify_version(package: Path):
    package_json = package / "package.json"
    if not package_json.exists():
        raise RuntimeError(f"OpenCLI package not found at {package}")
    result = run(
        [
            sys.executable,
            "-c",
            "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8'))['version'])",
            str(package_json),
        ]
    )
    version = result.stdout.strip()
    if version != EXPECTED_VERSION:
        raise RuntimeError(
            f"Expected OpenCLI {EXPECTED_VERSION}, found {version}. "
            "Review or regenerate the patches before applying."
        )


def backup_files(package: Path, patch_paths: list[Path]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = Path.home() / ".codex" / "backups" / f"opencli-reapply-{stamp}"
    for patch_path in patch_paths:
        for line in patch_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("+++ b/"):
                relative = line[6:].strip()
                source = package / relative
                if source.exists():
                    target = backup_root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    return backup_root


def apply_patch(package: Path, patch_path: Path):
    reverse = run(
        ["git", "apply", "--reverse", "--check", str(patch_path)],
        cwd=package,
        check=False,
    )
    if reverse.returncode == 0:
        return "already-applied"
    run(["git", "apply", "--check", str(patch_path)], cwd=package)
    run(["git", "apply", str(patch_path)], cwd=package)
    return "applied"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check patches without writing")
    args = parser.parse_args()

    package = package_root()
    verify_version(package)
    patches = sorted(PATCH_DIR.glob("*.patch"))
    if not patches:
        raise RuntimeError(f"No patches found in {PATCH_DIR}")

    if args.check:
        for patch_path in patches:
            reverse = run(
                ["git", "apply", "--reverse", "--check", str(patch_path)],
                cwd=package,
                check=False,
            )
            forward = run(
                ["git", "apply", "--check", str(patch_path)],
                cwd=package,
                check=False,
            )
            if reverse.returncode != 0 and forward.returncode != 0:
                raise RuntimeError(f"Patch does not match current package: {patch_path.name}")
        print(f"OpenCLI {EXPECTED_VERSION}: {len(patches)} patches are applicable")
        return 0

    backup = backup_files(package, patches)
    results = []
    for patch_path in patches:
        results.append((patch_path.name, apply_patch(package, patch_path)))
    for filename in (
        "clis/facebook/profile.js",
        "clis/twitter/auth.js",
        "clis/xiaohongshu/search.js",
        "clis/xueqiu/hot.js",
    ):
        source = package / filename
        if source.exists():
            run(["node", "--check", str(source)])
    print(f"Backup: {backup}")
    for name, result in results:
        print(f"{result}: {name}")
    opencli = shutil.which("opencli")
    if opencli:
        subprocess.run([opencli, "daemon", "restart"], check=False)
    else:
        print("warning: opencli not found; restart the daemon manually", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
