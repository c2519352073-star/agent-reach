from agent_reach.config import Config
from agent_reach.utils.paths import get_agent_reach_download_dir


def test_download_dir_env_override(tmp_path, monkeypatch):
    target = tmp_path / "agent-reach-output"
    monkeypatch.setenv("AGENT_REACH_DOWNLOAD_DIR", str(target))

    assert get_agent_reach_download_dir() == target
    assert target.is_dir()


def test_download_dir_config_override(tmp_path, monkeypatch):
    target = tmp_path / "configured-output"
    monkeypatch.delenv("AGENT_REACH_DOWNLOAD_DIR", raising=False)
    config = Config(config_path=tmp_path / "config.yaml")
    config.set("download_dir", str(target))

    assert get_agent_reach_download_dir(config) == target
    assert target.is_dir()


def test_download_dir_env_beats_config(tmp_path, monkeypatch):
    env_target = tmp_path / "env-output"
    config_target = tmp_path / "config-output"
    monkeypatch.setenv("AGENT_REACH_DOWNLOAD_DIR", str(env_target))
    config = Config(config_path=tmp_path / "config.yaml")
    config.set("download_dir", str(config_target))

    assert get_agent_reach_download_dir(config) == env_target
    assert not config_target.exists()
