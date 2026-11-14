"""文案完整性。两条守卫能挡住九成的文案事故。"""

from __future__ import annotations

import json
import re

from app import i18n, paths

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _load(code: str) -> dict[str, str]:
    path = paths.LOCALES_DIR / f"{code}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_locale_has_the_same_keys():
    zh = set(_load("zh-CN"))
    en = set(_load("en-US"))
    assert zh == en, f"只在中文里: {sorted(zh - en)}; 只在英文里: {sorted(en - zh)}"


def test_placeholders_match_the_default_language():
    zh = _load("zh-CN")
    en = _load("en-US")
    for key, text in zh.items():
        expected = set(_PLACEHOLDER.findall(text))
        actual = set(_PLACEHOLDER.findall(en.get(key, "")))
        assert expected == actual, f"{key}: {expected} != {actual}"


def test_missing_key_returns_the_key():
    assert i18n.t("no.such.key") == "no.such.key"


def test_placeholders_are_filled():
    text = i18n.t("page.indicator", current=2, total=9)
    assert "2" in text and "9" in text


def test_unknown_placeholder_does_not_raise():
    assert i18n.t("page.indicator", wrong=1)


def test_switch_to_english():
    i18n.set_language("en-US")
    assert i18n.t("app.title") == "PDF Image Editor"
    assert i18n.current() == "en-US"


def test_invalid_language_falls_back():
    assert i18n.set_language("xx-YY") == "en-US"


def test_available_lists_both():
    assert {"zh-CN", "en-US"} <= set(i18n.available())


def test_strings_falls_back_to_the_default_language(monkeypatch):
    """前端只有一张表、没有回退逻辑，缺键必须由后端补齐。"""
    monkeypatch.setitem(i18n._catalog, "xx-XX", {"app.title": "X"})
    table = i18n.strings("xx-XX")
    assert table["app.title"] == "X"
    assert table["toolbar.open"] == "Open"


def test_app_title_is_the_current_name():
    assert i18n.t("app.title") == "PDF 图像编辑器"
