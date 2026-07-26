"""数据目录迁移链测试：~/.verkee/verify ← ~/.verkeep/verify ← ~/.ai-verify"""

import shutil

import pytest

from verkee_verify import paths


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Redirect HOME_DIR/LEGACY_HOMES to tmp_path and reset _migrated."""
    home = tmp_path / ".verkee" / "verify"
    legacies = [tmp_path / ".verkeep" / "verify", tmp_path / ".ai-verify"]
    monkeypatch.setattr(paths, "HOME_DIR", home)
    monkeypatch.setattr(paths, "LEGACY_HOMES", legacies)
    monkeypatch.setattr(paths, "_migrated", False)
    return home, legacies


def test_existing_home_no_migration(fake_home, capsys):
    home, _ = fake_home
    home.mkdir(parents=True)
    assert paths.verify_home() == home
    assert capsys.readouterr().err == ""


def test_migrate_from_verkeep(fake_home, capsys):
    home, legacies = fake_home
    legacies[0].mkdir(parents=True)
    (legacies[0] / "config.yaml").write_text("x: 1", encoding="utf-8")
    assert paths.verify_home() == home
    assert (home / "config.yaml").is_file()
    assert not legacies[0].exists()
    err = capsys.readouterr().err
    assert "已自动迁移" in err and ".verkeep" in err


def test_migrate_from_ai_verify(fake_home, capsys):
    home, legacies = fake_home
    legacies[1].mkdir(parents=True)
    assert paths.verify_home() == home
    assert not legacies[1].exists()
    err = capsys.readouterr().err
    assert "已自动迁移" in err and ".ai-verify" in err


def test_verkeep_preferred_over_ai_verify(fake_home):
    home, legacies = fake_home
    for legacy in legacies:
        legacy.mkdir(parents=True)
        (legacy / "marker").write_text(legacy.name, encoding="utf-8")
    assert paths.verify_home() == home
    # 迁移链从新到旧，~/.verkeep/verify 优先，~/.ai-verify 原样保留
    assert (home / "marker").read_text(encoding="utf-8") == "verify"
    assert legacies[1].is_dir()


def test_idempotent_second_call(fake_home, capsys):
    home, legacies = fake_home
    legacies[0].mkdir(parents=True)
    assert paths.verify_home() == home
    capsys.readouterr()
    # 重置一次性标记后再调用：新目录已存在，不再重复迁移
    paths._migrated = False
    assert paths.verify_home() == home
    assert capsys.readouterr().err == ""


def test_migration_failure_falls_back_to_legacy(fake_home, capsys, monkeypatch):
    home, legacies = fake_home
    legacies[0].mkdir(parents=True)

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "move", boom)
    assert paths.verify_home() == legacies[0]
    assert "迁移失败" in capsys.readouterr().err
