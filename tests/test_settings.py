"""配置读写：夹取、未知键保留、损坏报错、原子写。"""

from __future__ import annotations

import json

import pytest

from app import settings
from app.errors import ConfigError


def test_first_load_creates_defaults(temp_config):
    config = settings.load_app()
    assert config["language"] == "zh-CN"
    assert config["reference"]["right_mm"] == settings.DEFAULT_REFERENCE["right_mm"]
    assert (temp_config / "app.json").is_file()


def test_non_numeric_falls_back_to_default(temp_config):
    (temp_config / "app.json").write_text(
        json.dumps({"undo_limit": "many", "zoom": None}), encoding="utf-8"
    )
    config = settings.load_app()
    assert config["undo_limit"] == settings.DEFAULT_APP["undo_limit"]
    assert config["zoom"] == settings.DEFAULT_APP["zoom"]


def test_out_of_range_is_clamped(temp_config):
    (temp_config / "app.json").write_text(
        json.dumps({"undo_limit": 99999, "render_dpi_cap": 5, "zoom": -3}), encoding="utf-8"
    )
    config = settings.load_app()
    assert config["undo_limit"] == 500
    assert config["render_dpi_cap"] == 96
    assert config["zoom"] == 0.1


def test_unknown_keys_are_preserved(temp_config):
    payload = {"undo_limit": 50, "custom_field": {"keep": True}}
    (temp_config / "app.json").write_text(json.dumps(payload), encoding="utf-8")
    config = settings.load_app()
    assert config["custom_field"] == {"keep": True}


def test_bad_theme_falls_back(temp_config):
    (temp_config / "app.json").write_text(json.dumps({"theme": "neon"}), encoding="utf-8")
    assert settings.load_app()["theme"] == "light"


def test_corrupt_json_raises(temp_config):
    (temp_config / "app.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        settings.load_app()
    assert info.value.key == "error.config_unreadable"


def test_non_object_raises(temp_config):
    (temp_config / "app.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        settings.load_app()
    assert info.value.key == "error.config_not_object"


def test_atomic_write_leaves_no_temp_file(temp_config):
    settings.save_app({"undo_limit": 20})
    leftovers = [p.name for p in temp_config.iterdir() if ".tmp" in p.name]
    assert leftovers == []


def test_reference_defaults_and_clamp(temp_config):
    config = settings.load_reference()
    assert config["right_mm"] == settings.DEFAULT_REFERENCE["right_mm"]
    settings.save_reference({"left_mm": -10, "top_mm": "abc"})
    reloaded = settings.load_reference()
    assert reloaded["left_mm"] == 0.0
    assert reloaded["top_mm"] == settings.DEFAULT_REFERENCE["top_mm"]
    # 边距必须落在 app.json 里，不能另开一个文件
    stored = json.loads((temp_config / "app.json").read_text(encoding="utf-8"))
    assert stored["reference"]["left_mm"] == 0.0
    assert not (temp_config / "reference.json").exists()


def test_legacy_reference_is_migrated(temp_config):
    legacy = {
        "left_cm": 1.0,
        "top_cm": 1.0,
        "right_cm": 5.0,
        "bottom_cm": 1.0,
    }
    (temp_config / "reference_line.json").write_text(json.dumps(legacy), encoding="utf-8")
    config = settings.load_reference()
    assert config["left_mm"] == pytest.approx(10.0)
    assert config["right_mm"] == pytest.approx(50.0)
    stored = json.loads((temp_config / "app.json").read_text(encoding="utf-8"))
    assert stored["reference"]["right_mm"] == pytest.approx(50.0)
    assert not (temp_config / "reference_line.json").exists()


def test_reference_json_is_merged_into_app_json(temp_config):
    (temp_config / "app.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    (temp_config / "reference.json").write_text(json.dumps({"left_mm": 33}), encoding="utf-8")

    config = settings.load_app()

    assert config["reference"]["left_mm"] == pytest.approx(33)
    assert not (temp_config / "reference.json").exists()
    stored = json.loads((temp_config / "app.json").read_text(encoding="utf-8"))
    assert stored["reference"]["left_mm"] == pytest.approx(33)


def test_save_mode_is_dropped(temp_config):
    (temp_config / "app.json").write_text(json.dumps({"save_mode": "raster"}), encoding="utf-8")
    config = settings.load_app()
    assert "save_mode" not in config
    assert "save_mode" not in json.loads((temp_config / "app.json").read_text(encoding="utf-8"))


def test_keybindings_are_normalized(temp_config):
    (temp_config / "app.json").write_text(
        json.dumps(
            {
                "keybindings": {
                    "global": {"save": "Ctrl+S", "bad": 123, "empty": "  "},
                    "split": {"split_keep": "1"},
                    "nonsense": "not a dict",
                }
            }
        ),
        encoding="utf-8",
    )
    config = settings.load_app()
    assert config["keybindings"]["global"] == {"save": "Ctrl+S"}
    assert config["keybindings"]["split"] == {"split_keep": "1"}
    assert "nonsense" not in config["keybindings"]


def test_keybindings_reject_non_dict(temp_config):
    (temp_config / "app.json").write_text(json.dumps({"keybindings": ["a", "b"]}), encoding="utf-8")
    assert settings.load_app()["keybindings"] == {}


def test_show_inspector_default_and_clamp(temp_config):
    assert settings.load_app()["show_inspector"] is True
    (temp_config / "app.json").write_text(json.dumps({"show_inspector": "false"}), encoding="utf-8")
    assert settings.load_app()["show_inspector"] is False
