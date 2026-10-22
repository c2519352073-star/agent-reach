import subprocess

import pytest

from agent_reach import update_local


def test_check_only_reports_update_without_merging(monkeypatch, tmp_path, capsys):
    status = update_local.UpdateStatus(
        root=tmp_path,
        branch="codex/local",
        head="abc123",
        upstream="def456",
        behind=2,
        ahead=1,
    )
    monkeypatch.setattr(update_local, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(update_local, "_ensure_clean", lambda root: None)
    monkeypatch.setattr(update_local, "_check_opencli_patches", lambda root: None)
    monkeypatch.setattr(update_local, "_fetch_status", lambda root: status)

    assert update_local.update_local(check_only=True) == 0
    output = capsys.readouterr().out
    assert "Update available" in output
    assert "agent-reach update-local" in output


def test_merge_conflict_aborts_and_restores_branch(monkeypatch, tmp_path):
    status = update_local.UpdateStatus(
        root=tmp_path,
        branch="codex/local",
        head="abc123",
        upstream="def456",
        behind=1,
        ahead=1,
    )
    calls = []

    def fake_run(args, *, cwd, check=True):
        calls.append(list(args))
        if args[:2] == ["git", "merge"] and "--abort" not in args:
            return subprocess.CompletedProcess(args, 1, "conflict\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(update_local, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(update_local, "_ensure_clean", lambda root: None)
    monkeypatch.setattr(update_local, "_check_opencli_patches", lambda root: None)
    monkeypatch.setattr(update_local, "_fetch_status", lambda root: status)
    monkeypatch.setattr(update_local, "_run", fake_run)

    with pytest.raises(update_local.UpdateError, match="Merge conflict"):
        update_local.update_local()

    assert ["git", "merge", "--abort"] in calls
