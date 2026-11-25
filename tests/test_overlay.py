"""文本框与荧光笔的落盘、读回与回收。

这些断言守的是「保存之后还认得自己画的东西」：文字要能被抽取、字体要是子集、
重开之后模型能原样还原、反复保存不会越存越多。
"""

from __future__ import annotations

import io

import pymupdf
import pytest

from app.core import overlay

MARK = overlay.MARK_PREFIX


def _open(instance, wait, path) -> None:
    started = instance.open_path(str(path), force=True)
    assert started["ok"] is True
    assert wait(instance, started["task"])["state"] == "ready"


def _save(instance, target) -> dict:
    result = instance.save_document(str(target))
    assert result["ok"] is True, result
    return result


def _text_object(snapshot) -> dict:
    for obj in snapshot["objects"]:
        if obj["kind"] == "text":
            return obj
    raise AssertionError("快照里没有文本框")


def test_text_is_written_as_real_page_text(editor, opened, tmp_path):
    instance, _server = editor
    opened()
    snapshot = instance.create_text(0, 90, 120, {"size": 14})
    obj = _text_object(snapshot)
    instance.update_text(obj["id"], [["混排文字", "simsun"], [" Latin", "times"]])

    target = tmp_path / "text.pdf"
    _save(instance, target)

    doc = pymupdf.open(target)
    try:
        page = doc[0]
        text = page.get_text()
        assert "混排文字" in text
        assert "Latin" in text
        fonts = [entry[3] for entry in doc.get_page_fonts(0, full=True)]
        # 子集字体的名字前面带六位大写前缀，例如 ABCDEE+SimSun。
        assert any("+" in name and "SimSun" in name for name in fonts)
        assert any("+" in name and "Times" in name for name in fonts)
    finally:
        doc.close()


def test_text_survives_reopen_and_keeps_its_style(editor, opened, wait, tmp_path):
    instance, _server = editor
    opened()
    snapshot = instance.create_text(0, 90, 120, {"size": 18, "color": "red", "line_height": 1.4})
    obj = _text_object(snapshot)
    instance.update_text(obj["id"], [["再来一次", "simkai"]])
    target = tmp_path / "again.pdf"
    _save(instance, target)

    # 重新打开这个文件：模型应该从 PDF 里的标记还原出来。
    _open(instance, wait, target)
    for index in range(instance.get_state()["doc"]["page_count"]):
        instance.load_page(index, 96)

    loaded = _text_object(instance.get_state())
    assert loaded["size"] == 18
    assert loaded["color"] == "red"
    assert loaded["line_height"] == pytest.approx(1.4)
    assert loaded["runs"] == [["再来一次", "simkai"]]


def test_saving_twice_does_not_duplicate_text(editor, opened, tmp_path):
    instance, _server = editor
    opened()
    snapshot = instance.create_text(0, 90, 120, {})
    obj = _text_object(snapshot)
    instance.update_text(obj["id"], [["只此一份", "simsun"]])

    target = tmp_path / "twice.pdf"
    _save(instance, target)
    _save(instance, target)

    doc = pymupdf.open(target)
    try:
        assert doc[0].get_text().count("只此一份") == 1
    finally:
        doc.close()


def test_deleting_a_text_box_removes_it_from_the_file(editor, opened, tmp_path):
    instance, _server = editor
    opened()
    snapshot = instance.create_text(0, 90, 120, {})
    obj = _text_object(snapshot)
    instance.update_text(obj["id"], [["要删掉的", "simsun"]])

    target = tmp_path / "deleted.pdf"
    _save(instance, target)

    instance.delete_objects([obj["id"]])
    _save(instance, target)

    doc = pymupdf.open(target)
    try:
        text = doc[0].get_text()
        assert "要删掉的" not in text
        # 原有的文字层不能被误伤。
        assert "Hello text layer" in text
    finally:
        doc.close()


def test_highlight_multiplies_instead_of_covering(editor, wait, tmp_path):
    """荧光带压在黑底上不改变颜色，压在白纸上就是黄色。"""
    source = tmp_path / "bands.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.draw_rect(pymupdf.Rect(0, 0, 150, 200), color=None, fill=(0, 0, 0))
    page.draw_rect(pymupdf.Rect(150, 0, 300, 200), color=None, fill=(1, 1, 1))
    doc.save(source)
    doc.close()

    instance, _server = editor
    _open(instance, wait, source)
    instance.load_page(0, 96)

    snapshot = instance.create_highlight(0, 40, 80, 200, "yellow")
    band = next(o for o in snapshot["objects"] if o["kind"] == "highlight")
    assert band["h"] == pytest.approx(15 * 0.75)

    target = tmp_path / "band-out.pdf"
    _save(instance, target)

    doc = pymupdf.open(target)
    try:
        pix = doc[0].get_pixmap(dpi=72)
        over_black = pix.pixel(60, 88)
        over_white = pix.pixel(220, 88)
        assert over_black == (0, 0, 0)
        assert over_white[0] > 240 and over_white[2] < 120  # 偏黄
    finally:
        doc.close()


def test_overlay_is_removed_before_redaction(editor, opened, tmp_path):
    """覆盖层撤掉之后，页面上的图片还能正常被 redaction + 重新插入。"""
    instance, _server = editor
    opened()
    snapshot = instance.create_text(0, 90, 120, {})
    obj = _text_object(snapshot)
    instance.update_text(obj["id"], [["第一版", "simsun"]])

    target = tmp_path / "twice.pdf"
    _save(instance, target)

    # 第二遍：换掉文字再存，图片不能被覆盖层连累。
    instance.update_text(obj["id"], [["第二版", "simsun"]])
    _save(instance, target)

    doc = pymupdf.open(target)
    try:
        text = doc[0].get_text()
        assert "第一版" not in text
        assert "第二版" in text
        assert len(doc[0].get_images()) == 1
    finally:
        doc.close()


def test_markdown_page_without_text_does_not_gain_a_stream(editor, opened, tmp_path):
    """没有文本框/荧光笔的页，保存后不该多出任何覆盖层。"""
    instance, _server = editor
    opened()
    target = tmp_path / "plain.pdf"
    _save(instance, target)

    doc = pymupdf.open(target)
    try:
        assert overlay.read(doc, doc[0]) == []
        for xref in doc[0].get_contents():
            assert not (doc.xref_stream(xref) or b"").startswith(MARK)
    finally:
        doc.close()


def test_cropped_page_keeps_text_in_place(editor, wait, tmp_path):
    """cropbox 原点不为 0 的页，文字要落在画布坐标上，不能整体偏移。"""
    source = tmp_path / "cropped.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((50, 60), "CROP", fontsize=14)
    page.set_cropbox(pymupdf.Rect(20, 30, 380, 270))
    doc.save(source)
    doc.close()

    instance, _server = editor
    _open(instance, wait, source)
    instance.load_page(0, 96)

    snapshot = instance.create_text(0, 20, 40, {"size": 14})
    obj = _text_object(snapshot)
    instance.update_text(obj["id"], [["左上角", "simhei"]])

    target = tmp_path / "cropped-out.pdf"
    _save(instance, target)

    doc = pymupdf.open(target)
    try:
        blocks = doc[0].get_text("dict")["blocks"]
        spans = [
            span for block in blocks for line in block.get("lines", []) for span in line["spans"]
        ]
        placed = next(span for span in spans if "左上角" in span["text"])
        x0, y0 = placed["bbox"][0], placed["bbox"][1]
        assert x0 == pytest.approx(20.0, abs=1.0)
        # 落点 (20, 40) 就是文本框左上角；首行字形顶边比它低约一个字高的上沿留白。
        assert y0 == pytest.approx(40.8, abs=1.5)
    finally:
        doc.close()


def test_text_transform_only_accepts_width(editor, opened):
    """文本框的高度永远是算出来的：拖不出「拉高」。"""
    instance, _server = editor
    opened()
    snapshot = instance.create_text(0, 90, 120, {"size": 14})
    obj = _text_object(snapshot)
    instance.update_text(obj["id"], [["一行字", "simsun"]])

    changed = instance.commit_transform(
        [{"id": obj["id"], "page": 0, "x": 60, "y": 60, "w": 200, "h": 400}]
    )
    updated = _text_object(changed)
    assert updated["x"] == pytest.approx(60)
    assert updated["w"] == pytest.approx(200)
    assert updated["h"] < 60  # 一行字撑不出 400pt 高


def test_highlight_transform_ignores_size(editor, opened):
    """荧光带只能挪位置，宽高不动。"""
    instance, _server = editor
    opened()
    snapshot = instance.create_highlight(0, 40, 80, 120, "yellow")
    band = next(o for o in snapshot["objects"] if o["kind"] == "highlight")
    before = (band["w"], band["h"])

    changed = instance.commit_transform(
        [{"id": band["id"], "page": 0, "x": 80, "y": 120, "w": 400, "h": 300}]
    )
    updated = next(o for o in changed["objects"] if o["id"] == band["id"])
    assert updated["x"] == pytest.approx(80)
    assert updated["y"] == pytest.approx(120)
    assert (updated["w"], updated["h"]) == pytest.approx(before)


def test_empty_text_box_is_dropped(editor, opened):
    instance, _server = editor
    opened()
    snapshot = instance.create_text(0, 90, 120, {})
    obj = _text_object(snapshot)
    after = instance.update_text(obj["id"], [["   ", "simsun"]])
    assert all(item["id"] != obj["id"] for item in after["objects"])


def test_text_can_be_undone(editor, opened):
    instance, _server = editor
    opened()
    snapshot = instance.create_text(0, 90, 120, {})
    obj = _text_object(snapshot)
    instance.update_text(obj["id"], [["可撤销", "simsun"]])
    assert _text_object(instance.get_state())["runs"] == [["可撤销", "simsun"]]

    instance.undo()
    assert _text_object(instance.get_state())["runs"] == [["", "msyh"]]


def test_background_render_excludes_our_text(editor, opened, wait, tmp_path):
    """背景图必须画成「没有我们覆盖层」的样子。

    覆盖层已经由前端用 DOM 画了一遍；背景再画一遍，文字就等于被烘焙进背景，
    移动文本框时原位会留下一个擦不掉的残影。
    """
    instance, _server = editor
    opened()
    instance.load_page(0, 96)
    snapshot = instance.create_text(0, 60, 400, {"size": 28})
    obj = _text_object(snapshot)
    instance.update_text(obj["id"], [["背景不该有", "simhei"]])

    target = tmp_path / "clean-background.pdf"
    _save(instance, target)
    # 重新打开：这时文件里已经有我们的覆盖层，正好检验渲染会不会把它算进背景。
    _open(instance, wait, target)
    instance.load_page(0, 96)

    png = instance.render_page(0, 96)
    # 直接解 PNG 的像素：先当图片文档再 get_pixmap 会按图片 DPI 重采样，
    # 坐标和渲染时的像素对不上。
    pix = pymupdf.Pixmap(io.BytesIO(png))
    scale = 96 / 72
    x0 = max(0, int(60 * scale) - 2)
    y0 = max(0, int(400 * scale) - 2)
    x1 = min(pix.width, int(170 * scale) + 2)
    y1 = min(pix.height, int(432 * scale) + 2)
    dark = [
        (x, y) for y in range(y0, y1) for x in range(x0, x1) if pix.pixel(x, y) != (255, 255, 255)
    ]
    assert dark == []

    # 背景不画，不等于文件里没有：文字仍然是可以抽取的页面内容。
    doc = pymupdf.open(target)
    try:
        assert "背景不该有" in doc[0].get_text()
    finally:
        doc.close()


def test_hidden_detaches_the_overlay_only_while_rendering():
    """渲染背景时只摘内容流，退出后原样挂回；覆盖层不能因此丢掉。"""
    from app.models import Rect, TextObject, TextRun

    doc = pymupdf.open()
    try:
        page = doc.new_page(width=200, height=120)
        obj = TextObject(
            id="t-test",
            page=0,
            rect=Rect(20, 20, 120, 24),
            runs=[TextRun("检查", "simhei")],
            size_px=28,
        )
        assert overlay.draw(doc, page, [obj]) is True
        before = page.get_contents()
        assert before  # 至少有一条属于我们的覆盖层流

        with overlay.hidden(doc, page):
            assert page.get_contents() == before[:-1]
            pix = page.get_pixmap(dpi=72)
            assert not any(
                pix.pixel(x, y) != (255, 255, 255) for x in range(20, 140) for y in range(20, 50)
            )

        assert page.get_contents() == before
        # 挂回来之后字又在了，JSON 也还读得出来。
        pix = page.get_pixmap(dpi=72)
        assert any(
            pix.pixel(x, y) != (255, 255, 255) for x in range(20, 140) for y in range(20, 50)
        )
        assert overlay.read(doc, page)
    finally:
        doc.close()


def _image_pages(tmp_path, name: str) -> pymupdf.Document:
    """三页、每页都有文字和一张图，用来验证覆盖层不会把页面资源挖空。"""
    doc = pymupdf.open()
    for index in range(3):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"PAGE{index + 1} text", fontsize=16)
        pix = pymupdf.Pixmap(pymupdf.csRGB, 40, 30, b"\xff\x00\x00" * 1200, False)
        page.insert_image(pymupdf.Rect(100, 100, 300, 250), pixmap=pix)
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return pymupdf.open(path)


def _resources_xref(doc, page) -> int:
    kind, value = doc.xref_get_key(page.xref, "Resources")
    assert kind == "xref"
    return int(value.split()[0])


def _note(page: int = 1):
    from app.models import Rect, TextObject, TextRun

    return TextObject(
        id=f"t{page}",
        page=page,
        rect=Rect(60, 300, 200, 30),
        runs=[TextRun("overlay note", "msyh")],
        z=50,
    )


def test_draw_works_when_resources_are_inherited(tmp_path):
    """``/Resources`` 挂在父节点上（页面继承）时也要认得出刚挂上去的 XObject。

    认不出来的后果不是「画不上」而是「画上了却没写标记」：文字被烤进页面，
    模型里读不回来，下一次保存还会当它不存在。
    """
    doc = _image_pages(tmp_path, "inherit-src.pdf")
    try:
        shared = _resources_xref(doc, doc[0])
        pages_xref = int(doc.xref_get_key(doc.pdf_catalog(), "Pages")[1].split()[0])
        doc.xref_set_key(pages_xref, "Resources", f"{shared} 0 R")
        for index in range(doc.page_count):
            doc.xref_set_key(doc[index].xref, "Resources", "null")
        out = tmp_path / "inherit.pdf"
        doc.save(str(out), garbage=3, deflate=True)
    finally:
        doc.close()

    doc = pymupdf.open(out)
    try:
        page = doc[1]
        assert overlay.draw(doc, page, [_note()]) is True
        assert len(overlay.read(doc, page)) == 1
        # 页面自己不能被写成一个只含 XObject 的 Resources：那会把继承来的
        # 字体和图片全挡住，整页内容看起来就没了。
        assert len(page.get_image_info(xrefs=True)) == 1
        assert "PAGE2 text" in page.get_text()
    finally:
        doc.close()


def test_draw_works_when_the_xobject_dict_is_indirect(tmp_path):
    """``/Resources/XObject`` 是间接对象时，资源字典本身读不到名字。"""
    doc = _image_pages(tmp_path, "indirect-src.pdf")
    try:
        for index in range(doc.page_count):
            page = doc[index]
            res = _resources_xref(doc, page)
            kind, value = doc.xref_get_key(res, "XObject")
            assert kind == "dict"
            fresh = doc.get_new_xref()
            doc.update_object(fresh, value)
            doc.xref_set_key(res, "XObject", f"{fresh} 0 R")
        out = tmp_path / "indirect.pdf"
        doc.save(str(out), garbage=3, deflate=True)
    finally:
        doc.close()

    doc = pymupdf.open(out)
    try:
        page = doc[1]
        assert overlay.draw(doc, page, [_note()]) is True
        assert len(overlay.read(doc, page)) == 1
        assert len(page.get_image_info(xrefs=True)) == 1
    finally:
        doc.close()
