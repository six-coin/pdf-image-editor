"""配置读写：夹取、未知键保留、损坏报错、原子写。"""

from __future__ import annotations

import json

import pytest

from app import paths, settings
from app.errors import ConfigError


def test_first_load_creates_defaults(temp_config):
    config = settings.load_app()
    assert config["language"] == "zh-CN"
    assert config["reference"]["right_mm"] == settings.DEFAULT_REFERENCE["right_mm"]
    assert (temp_config / "app.json").is_file()


def test_non_numeric_falls_back_to_default(temp_config):
    (temp_config / "app.json").write_text(
        json.dumps({"undo_limit": "many", "preprocess_threshold": None}), encoding="utf-8"
    )
    config = settings.load_app()
    assert config["undo_limit"] == settings.DEFAULT_APP["undo_limit"]
    assert config["preprocess_threshold"] == settings.DEFAULT_APP["preprocess_threshold"]


def test_out_of_range_is_clamped(temp_config):
    (temp_config / "app.json").write_text(
        json.dumps({"undo_limit": 99999, "render_dpi_cap": 5, "preprocess_threshold": -3}),
        encoding="utf-8",
    )
    config = settings.load_app()
    assert config["undo_limit"] == 500
    assert config["render_dpi_cap"] == 96
    assert config["preprocess_threshold"] == 0


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
    assert reloaded["left_mm"] == [0.0]
    assert reloaded["top_mm"] == settings.DEFAULT_REFERENCE["top_mm"]
    # 边距必须落在 app.json 里，不能另开一个文件
    stored = json.loads((temp_config / "app.json").read_text(encoding="utf-8"))
    assert stored["reference"]["left_mm"] == [0.0]
    assert not (temp_config / "reference.json").exists()


def test_reference_accepts_a_comma_list(temp_config):
    """一条边上可以有多条参考线：输入是逗号分隔，存下来是升序去重的列表。"""
    settings.save_reference({"right_mm": "50, 10, 10", "left_mm": [30, 5]})
    reloaded = settings.load_reference()
    assert reloaded["right_mm"] == [10.0, 50.0]
    assert reloaded["left_mm"] == [5.0, 30.0]


def test_reference_old_scalar_becomes_a_list(temp_config):
    """老配置里是一个数字，读进来要包成单元素列表，不能丢。"""
    (temp_config / "app.json").write_text(
        json.dumps({"reference": {"right_mm": 50, "left_mm": 12.5}}), encoding="utf-8"
    )
    config = settings.load_reference()
    assert config["right_mm"] == [50.0]
    assert config["left_mm"] == [12.5]


def test_reference_rejects_garbage(temp_config):
    settings.save_reference({"bottom_mm": "abc, ,", "top_mm": [None, "x", 20]})
    reloaded = settings.load_reference()
    assert reloaded["bottom_mm"] == settings.DEFAULT_REFERENCE["bottom_mm"]
    assert reloaded["top_mm"] == [20.0]


def test_legacy_reference_is_migrated(temp_config):
    legacy = {
        "left_cm": 1.0,
        "top_cm": 1.0,
        "right_cm": 5.0,
        "bottom_cm": 1.0,
    }
    (temp_config / "reference_line.json").write_text(json.dumps(legacy), encoding="utf-8")
    config = settings.load_reference()
    assert config["left_mm"] == [pytest.approx(10.0)]
    assert config["right_mm"] == [pytest.approx(50.0)]
    stored = json.loads((temp_config / "app.json").read_text(encoding="utf-8"))
    assert stored["reference"]["right_mm"] == [pytest.approx(50.0)]
    assert not (temp_config / "reference_line.json").exists()


def test_reference_json_is_merged_into_app_json(temp_config):
    (temp_config / "app.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    (temp_config / "reference.json").write_text(json.dumps({"left_mm": 33}), encoding="utf-8")

    config = settings.load_app()

    assert config["reference"]["left_mm"] == [pytest.approx(33)]
    assert not (temp_config / "reference.json").exists()
    stored = json.loads((temp_config / "app.json").read_text(encoding="utf-8"))
    assert stored["reference"]["left_mm"] == [pytest.approx(33)]


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


def test_eight_handles_defaults_to_on(temp_config):
    assert settings.load_app()["eight_handles"] is True


def test_eight_handles_can_be_turned_off(temp_config):
    (temp_config / "app.json").write_text(json.dumps({"eight_handles": "off"}), encoding="utf-8")
    assert settings.load_app()["eight_handles"] is False


def test_backup_retention_default_and_clamp(temp_config):
    assert settings.load_app()["backup_retention_days"] == 30

    (temp_config / "app.json").write_text(
        json.dumps({"backup_retention_days": 0}), encoding="utf-8"
    )
    assert settings.load_app()["backup_retention_days"] == 1

    (temp_config / "app.json").write_text(
        json.dumps({"backup_retention_days": "forever"}), encoding="utf-8"
    )
    assert settings.load_app()["backup_retention_days"] == 30

    (temp_config / "app.json").write_text(
        json.dumps({"backup_retention_days": 99999}), encoding="utf-8"
    )
    assert settings.load_app()["backup_retention_days"] == 3650


def test_preview_language_does_not_write_config(editor):
    """首次运行的语言下拉框只换内存：写了 app.json 就等于跳过了首次运行。"""
    instance, _ = editor
    before = paths.APP_CONFIG_PATH.read_bytes()

    result = instance.preview_language("en-US")

    assert result["language"] == "en-US"
    assert paths.APP_CONFIG_PATH.read_bytes() == before


def test_font_and_color_keys_match_core_tables():
    """settings 是基础层，不 import core，所以键表在这里再列了一遍——两边必须一致。"""
    from app.core import fonts, palette

    assert set(settings.FONT_KEYS) == set(fonts.families())
    assert set(settings.TEXT_COLOR_KEYS) == set(palette.TEXT_COLORS)
    assert set(settings.HIGHLIGHT_COLOR_KEYS) == set(palette.HIGHLIGHT_COLORS)


def test_text_and_highlight_defaults(temp_config):
    config = settings.load_app()
    assert config["text_font"] == "msyh"
    assert config["text_size_px"] == 14
    assert config["text_color"] == "blue"
    assert config["text_width_mm"] == pytest.approx(40.0)
    assert config["text_line_height"] == pytest.approx(1.15)
    assert config["highlight_height_px"] == 15
    assert config["highlight_color"] == "yellow"


def test_bad_text_defaults_are_clamped(temp_config):
    settings.save_app(
        {
            "text_font": "comic",
            "text_size_px": 9999,
            "text_color": "pink",
            "text_width_mm": -5,
            "text_line_height": 99,
            "highlight_height_px": 0,
            "highlight_color": "cyan",
        }
    )
    config = settings.load_app()
    assert config["text_font"] == "msyh"
    assert config["text_size_px"] == 200
    assert config["text_color"] == "blue"
    assert config["text_width_mm"] == pytest.approx(10.0)
    assert config["text_line_height"] == pytest.approx(3.0)
    assert config["highlight_height_px"] == 4
    assert config["highlight_color"] == "yellow"


def test_align_defaults_are_independent_of_reference(temp_config):
    """对齐线默认是五条参考线再加左边 85mm，且和参考线分开存。"""
    config = settings.load_app()
    assert config["align"] == {
        "left_mm": [10.0, 85.0],
        "top_mm": [10.0],
        "right_mm": [10.0, 50.0],
        "bottom_mm": [10.0],
    }
    settings.save_align({"left_mm": "85, 10, 10"})
    assert settings.load_align()["left_mm"] == [10.0, 85.0]
    # 改对齐线不该顺手把参考线也改了。
    assert settings.load_reference()["left_mm"] == [10.0]


def test_align_rejects_garbage_and_keeps_defaults(temp_config):
    settings.save_align({"top_mm": "abc, ,", "right_mm": [None, "x", 20]})
    reloaded = settings.load_align()
    assert reloaded["top_mm"] == settings.DEFAULT_ALIGN["top_mm"]
    assert reloaded["right_mm"] == [20.0]
