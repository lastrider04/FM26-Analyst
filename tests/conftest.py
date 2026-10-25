import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import app_config  # noqa: E402

TEST_CLUB = 1001    # the club id the synthetic snapshots use


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets its own empty data folder, so none can read or change the real data/ (config, history)."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(app_config, "DATA", data)
    monkeypatch.setattr(app_config, "CONFIG_PATH", data / "config.json")
    monkeypatch.setattr(app_config, "DB_PATH", data / "fm_analyst.db")
    monkeypatch.setattr(app_config, "SNAPSHOT_DIR", data / "snapshots")
    # a fresh install has no club until it's chosen; the tests act as if one was
    monkeypatch.setitem(app_config.DEFAULTS, "club_id", TEST_CLUB)
