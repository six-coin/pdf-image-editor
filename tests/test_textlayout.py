"""文本排版：换行、行高、基线。

这里断言的是「排版规则本身」，不是像素——但每条都对应屏幕与 PDF 共用的那份
几何数据，错一条两边就对不上。
"""

from __future__ import annotations

import pytest

from app.core import textlayout
from app.core.textlayout import Run, layout

PX = textlayout.PX_TO_PT


def test_empty_text_still_has_one_line():
    lines, height = layout([], 200.0, 14, 1.15)
    assert len(lines) == 1
    assert height == pytest.approx(14 * 1.15 * PX)


def test_line_height_is_a_multiple_of_the_font_size():
    _lines, height = layout([Run("一行")], 200.0, 20, 1.5)
    assert height == pytest.approx(20 * 1.5 * PX)


def test_cjk_breaks_between_characters():
    # 14px 的汉字宽 10.5pt，宽度 40pt 只放得下 3 个字。
    lines, _height = layout([Run("一二三四五六")], 40.0, 14, 1.2)
    assert len(lines) == 2
    assert "".join(run.text for run in lines[0].runs) == "一二三"
    assert "".join(run.text for run in lines[1].runs) == "四五六"


def test_latin_breaks_between_words():
    lines, _height = layout([Run("alpha beta gamma")], 60.0, 14, 1.2)
    joined = ["".join(run.text for run in line.runs) for line in lines]
    assert joined == ["alpha beta", "gamma"]


def test_trailing_space_is_dropped_at_a_break():
    lines, _height = layout([Run("alpha beta gamma")], 60.0, 14, 1.2)
    assert not lines[0].runs[-1].text.endswith(" ")


def test_explicit_newline_starts_a_new_line():
    lines, _height = layout([Run("甲\n乙")], 400.0, 14, 1.2)
    assert len(lines) == 2
    assert lines[0].runs[0].text == "甲"
    assert lines[1].runs[0].text == "乙"


def test_trailing_newline_keeps_an_empty_line():
    lines, _height = layout([Run("甲\n")], 400.0, 14, 1.2)
    assert len(lines) == 2
    assert lines[1].runs == ()


def test_long_word_is_hard_split():
    lines, _height = layout([Run("abcdefghijklmnop")], 30.0, 14, 1.2)
    assert len(lines) > 1
    for line in lines:
        assert sum(run.width for run in line.runs) <= 30.0 + 1e-6


def test_mixed_fonts_keep_their_own_run():
    lines, _height = layout([Run("汉字", "simsun"), Run("Latin", "times")], 400.0, 14, 1.2)
    fonts_used = [run.font for run in lines[0].runs]
    assert fonts_used == ["simsun", "times"]


def test_run_positions_are_cumulative():
    lines, _height = layout([Run("汉字", "simsun"), Run("A", "times")], 400.0, 14, 1.2)
    first, second = lines[0].runs
    assert first.x == pytest.approx(0.0)
    assert second.x == pytest.approx(first.width)


def test_baselines_step_by_the_line_height():
    lines, _height = layout([Run("一\n二\n三")], 400.0, 14, 1.2)
    step = lines[1].baseline - lines[0].baseline
    assert step == pytest.approx(14 * 1.2 * PX)


def test_baseline_sits_inside_the_first_line():
    lines, height = layout([Run("一")], 400.0, 14, 1.2)
    assert 0 < lines[0].baseline < height


def test_width_is_respected_for_cjk():
    lines, _height = layout([Run("一二三四五")], 21.0, 14, 1.2)
    assert len(lines) == 3  # 每行两个字
