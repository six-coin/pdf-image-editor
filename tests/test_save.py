"""保存：文字保全、z 序、失败不毁源文件、备份、跨页拖动。

``test_text_survives_roundtrip`` 是整个项目最贵那个 bug 的回归测试。
"""

from __future__ import annotations

import os
import time
from datetime import date

import pymupdf
import pytest

from app.core import overlay
from app.core.document import PdfDocument
from app.core.save import save, sweep_backups
from app.errors import SaveError
from app.models import DocumentState, Rect, TextObject, TextRun


def _state(doc: PdfDocument) -> DocumentState:
    state = DocumentState(path=doc.path)
    state.pages = [doc.page_info(i) for i in range(doc.page_count)]
    state.objects = [o for i in range(doc.page_count) for o in doc.editable_images(i)]
    return state


def test_text_survives_roundtrip(pdf_factory, store, tmp_path):
    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)

    dst = tmp_path / "out.pdf"
    report = save(src, dst, state, store)

    assert report.ok
    assert report.replaced == 1
    out = pymupdf.open(dst)
    assert "Hello text layer" in out[0].get_text()
    assert len(out[0].get_image_info(xrefs=True)) == 1
    assert out[0].rect.width == pytest.approx(595)
    out.close()
    doc.close()


def test_moved_image_lands_at_new_position(pdf_factory, store, tmp_path):
    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    state.objects[0].rect = Rect(400, 500, 120, 90)

    dst = tmp_path / "out.pdf"
    save(src, dst, state, store)

    out = pymupdf.open(dst)
    infos = out[0].get_image_info(xrefs=True)
    assert len(infos) == 1
    bbox = infos[0]["bbox"]
    assert bbox[0] == pytest.approx(400, abs=1)
    assert bbox[1] == pytest.approx(500, abs=1)
    assert "Hello text layer" in out[0].get_text()
    out.close()
    doc.close()


def test_image_outside_the_page_keeps_its_position(pdf_factory, store, tmp_path):
    """单张图片允许被移到页外，保存时不能把它夹回页内或改大小。"""
    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    state.objects[0].rect = Rect(-150, -100, 120, 90)

    dst = tmp_path / "out.pdf"
    save(src, dst, state, store)

    out = pymupdf.open(dst)
    infos = out[0].get_image_info(xrefs=True)
    assert len(infos) == 1
    bbox = infos[0]["bbox"]
    assert bbox[0] == pytest.approx(-150, abs=1)
    assert bbox[1] == pytest.approx(-100, abs=1)
    assert bbox[2] - bbox[0] == pytest.approx(120, abs=1)
    assert bbox[3] - bbox[1] == pytest.approx(90, abs=1)
    out.close()
    doc.close()


def test_deleted_image_leaves_text_alone(pdf_factory, store, tmp_path):
    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    for obj in list(state.objects):
        state.mark_removed(obj.page, obj.src_rect)
    state.objects = []

    dst = tmp_path / "out.pdf"
    save(src, dst, state, store)

    out = pymupdf.open(dst)
    assert out[0].get_image_info(xrefs=True) == []
    assert "Hello text layer" in out[0].get_text()
    out.close()
    doc.close()


def test_z_order_is_preserved(pdf_factory, store, tmp_path):
    src = pdf_factory("in.pdf", images=2)
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    assert [o.z for o in state.objects] == [10, 11]
    state.objects[0].z = 20

    dst = tmp_path / "out.pdf"
    save(src, dst, state, store)

    out = pymupdf.open(dst)
    widths = [info["width"] for info in out[0].get_image_info(xrefs=True)]
    assert widths == [60, 40]
    out.close()
    doc.close()


def test_source_untouched_when_replace_fails(pdf_factory, store, monkeypatch):
    src = pdf_factory("in.pdf")
    before = src.read_bytes()
    doc = PdfDocument.open(src, store)
    state = _state(doc)

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(SaveError):
        save(src, src, state, store)

    assert src.read_bytes() == before
    assert not list(src.parent.glob("*.tmp-*"))
    doc.close()


def test_in_place_save_copies_a_dated_backup(pdf_factory, store, tmp_path):
    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    # Windows 上覆盖仍被打开的文件会失败，就地保存前必须先释放句柄。
    doc.close()

    backup_dir = tmp_path / "backup"
    save(src, src, state, store, backup_dir=backup_dir)

    stamp = date.today().strftime("%Y%m%d")
    assert (backup_dir / f"{stamp}-in.bak.pdf").is_file()
    # 备份搬去数据目录之后，源文件旁边不该再出现 .bak.pdf。
    assert not src.with_name("in.bak.pdf").exists()
    out = pymupdf.open(src)
    assert "Hello text layer" in out[0].get_text()
    out.close()


def test_in_place_save_keeps_a_numbered_backup_each_time(pdf_factory, store, tmp_path):
    """同名备份已经在了就往后排号：每次保存前的那一版都要留下来。"""
    src = pdf_factory("in.pdf")
    original = src.read_bytes()
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    doc.close()

    backup_dir = tmp_path / "backup"
    stamp = date.today().strftime("%Y%m%d")
    save(src, src, state, store, backup_dir=backup_dir)
    first = (backup_dir / f"{stamp}-in.bak.pdf").read_bytes()
    assert first == original

    # 第二次保存前把图挪个位置：第二份备份必须带着这一次改动之前的样子。
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    state.objects[0].rect = Rect(200, 200, 120, 90)
    doc.close()
    save(src, src, state, store, backup_dir=backup_dir)

    names = sorted(p.name for p in backup_dir.glob("*.pdf"))
    assert names == [f"{stamp}-in.bak.pdf", f"{stamp}-in.bak1.pdf"]
    # 第一份还是最初的样子，没有被覆盖。
    assert (backup_dir / f"{stamp}-in.bak.pdf").read_bytes() == original
    # bak1 是第二次保存前的文件：图还在原位。
    before = pymupdf.open(backup_dir / f"{stamp}-in.bak1.pdf")
    assert before[0].get_image_info(xrefs=True)[0]["bbox"][0] == pytest.approx(100, abs=1)
    before.close()

    # 再存一次：序号继续往后排，不会覆盖前两份。
    save(src, src, state, store, backup_dir=backup_dir)
    names = sorted(p.name for p in backup_dir.glob("*.pdf"))
    assert names == [
        f"{stamp}-in.bak.pdf",
        f"{stamp}-in.bak1.pdf",
        f"{stamp}-in.bak2.pdf",
    ]


def test_save_as_leaves_no_backup(pdf_factory, store, tmp_path):
    """另存为不动原文件，也就没有要备份的东西。"""
    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)

    backup_dir = tmp_path / "backup"
    save(src, tmp_path / "out.pdf", state, store, backup_dir=backup_dir)

    assert not backup_dir.exists()
    doc.close()


def test_sweep_backups_drops_only_expired_files(tmp_path):
    root = tmp_path / "backup"
    root.mkdir()
    old = root / "old.bak.pdf"
    fresh = root / "fresh.bak.pdf"
    old.write_bytes(b"x")
    fresh.write_bytes(b"x")
    stale = time.time() - 31 * 86400
    os.utime(old, (stale, stale))

    removed = sweep_backups(root, 30)

    assert removed == 1
    assert not old.exists()
    assert fresh.is_file()


def test_out_of_page_image_keeps_its_rect(pdf_factory, store, tmp_path):
    """图片允许超出页面；保存时保留原矩形，由阅读器按页裁切。"""
    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    state.objects[0].rect = Rect(560, 800, 200, 200)

    dst = tmp_path / "out.pdf"
    report = save(src, dst, state, store)

    assert not any(w["code"] == "image_clamped" for w in report.warnings)
    out = pymupdf.open(dst)
    bbox = out[0].get_image_info(xrefs=True)[0]["bbox"]
    assert bbox[0] == pytest.approx(560, abs=1)
    assert bbox[1] == pytest.approx(800, abs=1)
    assert bbox[2] == pytest.approx(760, abs=1)
    assert bbox[3] == pytest.approx(1000, abs=1)
    out.close()
    doc.close()


def _page_text(page) -> str:
    """TextWriter 写出来的空格是不换行空格（\\xa0），比较前统一成普通空格。"""
    return page.get_text().replace("\xa0", " ")


def _overlay_pdf(tmp_path, pages: int = 3):
    """每一页都有本项目画的文本框，用来验证保存不会把它们弄丢。"""
    path = tmp_path / "overlay.pdf"
    doc = pymupdf.open()
    for index in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"PAGE{index + 1} text", fontsize=16)
        overlay.draw(
            doc,
            page,
            [
                TextObject(
                    id=f"t{index}",
                    page=index,
                    rect=Rect(60, 300, 200, 30),
                    runs=[TextRun(f"note {index + 1}", "msyh")],
                    z=50,
                )
            ],
        )
    doc.save(str(path), garbage=4, deflate=True)
    doc.close()
    return path


def test_save_keeps_overlays_on_pages_never_loaded(tmp_path, store):
    """没装载进模型的页，保存时不能动它的覆盖层。

    这是「保存之后某一页的文本框整页消失」的回归：以前对每一页都无条件撤掉
    覆盖层，没装载过的页在模型里一个对象都没有，撤掉就再也画不回去了。
    """
    src = _overlay_pdf(tmp_path)
    doc = PdfDocument.open(src, store)
    state = DocumentState(path=src, loaded={0})
    state.pages = [doc.page_info(i) for i in range(doc.page_count)]
    state.objects = doc.editable_images(0) + doc.overlay_objects(0)
    doc.close()

    dst = tmp_path / "out.pdf"
    report = save(src, dst, state, store)

    assert not [w for w in report.warnings if w["code"].startswith("overlay")]
    out = pymupdf.open(dst)
    for index in range(3):
        assert len(overlay.read(out, out[index])) == 1
        assert f"note {index + 1}" in _page_text(out[index])
    out.close()


def test_save_rewrites_overlays_on_loaded_pages(tmp_path, store):
    """装载过的页照常更新：改过的文字要写进去，删掉的框要消失。"""
    src = _overlay_pdf(tmp_path)
    doc = PdfDocument.open(src, store)
    state = DocumentState(path=src, loaded={0, 1})
    state.pages = [doc.page_info(i) for i in range(doc.page_count)]
    state.objects = doc.overlay_objects(0) + doc.overlay_objects(1)
    doc.close()

    first = [o for o in state.objects if o.page == 0][0]
    first.runs = [TextRun("changed text", "msyh")]
    state.objects = [o for o in state.objects if o.page != 1]

    dst = tmp_path / "out.pdf"
    save(src, dst, state, store)

    out = pymupdf.open(dst)
    assert "changed text" in _page_text(out[0])
    assert "note 1" not in _page_text(out[0])
    assert len(overlay.read(out, out[0])) == 1
    # 第 2 页装载过但框被删了：这一页的覆盖层要清掉。
    assert overlay.read(out, out[1]) == []
    assert "note 2" not in _page_text(out[1])
    # 第 3 页没装载：原样保留。
    assert "note 3" in _page_text(out[2])
    out.close()


def _annotated_pdf(tmp_path):
    """一页里同时有文字、图片、以及压在图上的批注。"""
    path = tmp_path / "annotated.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "Hello text layer", fontsize=16)
    pix = pymupdf.Pixmap(pymupdf.csRGB, 40, 30, b"\xff\x00\x00" * 1200, False)
    page.insert_image(pymupdf.Rect(100, 100, 300, 250), pixmap=pix)
    page.add_freetext_annot(pymupdf.Rect(320, 320, 470, 380), "note over nothing")
    page.add_freetext_annot(pymupdf.Rect(120, 120, 280, 180), "note over image")
    page.add_ink_annot([[(150, 400), (200, 430), (250, 400)]])
    doc.save(str(path))
    doc.close()
    return path


def test_annotations_survive_save(tmp_path, store):
    """redaction 会删掉落在矩形里的批注，必须靠摘挂 /Annots 保住。"""
    src = _annotated_pdf(tmp_path)
    doc = PdfDocument.open(src, store)
    state = _state(doc)

    dst = tmp_path / "out.pdf"
    save(src, dst, state, store)

    before = pymupdf.open(src)
    after = pymupdf.open(dst)
    assert len(list(before[0].annots())) == 3
    assert len(list(after[0].annots())) == 3
    assert [a.type[1] for a in after[0].annots()] == [a.type[1] for a in before[0].annots()]

    text = after[0].get_text()
    assert "Hello text layer" in text
    assert "note over image" in text
    assert "note over nothing" in text
    assert len(after[0].get_image_info(xrefs=True)) == 1

    before.close()
    after.close()
    doc.close()


def test_split_then_save_roundtrip(pdf_factory, store, tmp_path):
    """不开界面跑通整条链路：打开 → 切分 → 保存 → 重新打开校验。"""
    from app.core.split import build_split

    src = pdf_factory("in.pdf")
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    target = state.objects[0]
    pieces = build_split(state.objects, target.id, [0.5], [0.5], store)
    assert pieces is not None and len(pieces) == 4
    state.objects = [o for o in state.objects if o.id != target.id] + pieces

    dst = tmp_path / "split.pdf"
    report = save(src, dst, state, store)

    assert report.replaced == 4
    out = pymupdf.open(dst)
    assert "Hello text layer" in out[0].get_text()
    assert len(out[0].get_image_info(xrefs=True)) == 4
    out.close()
    doc.close()


def test_cross_page_move_erases_the_source(pdf_factory, store, tmp_path):
    """把图拖到第 2 页后保存：原页的那张必须被擦掉，否则一张变两张。"""
    src = pdf_factory("in.pdf", pages=2, images=1)
    doc = PdfDocument.open(src, store)
    state = _state(doc)
    obj = state.objects[0]
    obj.page = 1
    obj.rect = Rect(60, 60, 120, 90)

    dst = tmp_path / "out.pdf"
    save(src, dst, state, store)

    out = pymupdf.open(dst)
    assert out[0].get_image_info(xrefs=True) == []
    assert len(out[1].get_image_info(xrefs=True)) == 2
    out.close()
    doc.close()


@pytest.mark.parametrize("pixels", [(40, 20), (40, 40)], ids=["wide", "square"])
def test_aspect_ratio_survives_save(tmp_path, store, pixels):
    """改过长宽比的图，保存后重新打开必须还是那个矩形。

    ``insert_image`` 默认的 ``keep_proportion=True`` 会按图片原始比例把图居中塞进
    目标矩形：中心不变、短边不变，看起来就是「比例被还原」。PyMuPDF 2.x 起这对
    JPEG 和 PNG 一致生效，方图也不例外，所以样本要覆盖这两种像素比例。
    """
    width, height = pixels
    src = tmp_path / "ratio.pdf"
    pix = pymupdf.Pixmap(pymupdf.csRGB, width, height, b"\xff\x00\x00" * (width * height), False)
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(100, 100, 300, 200), stream=pix.tobytes("jpg"))
    doc.save(src)
    doc.close()

    handle = PdfDocument.open(src, store)
    obj = handle.editable_images(0)[0]
    # 造样本时用的是默认 keep_proportion，图会被缩进目标矩形（方图变成 100×100
    # 居中）。这里只确认读出了一张图，随后统一改成 3:1 再验证保存。
    assert obj.rect.w > 0 and obj.rect.h > 0

    obj.rect = Rect(100, 100, 300, 100)  # 3:1，像素是 2:1
    state = DocumentState(path=src, objects=[obj])
    out = tmp_path / "ratio-out.pdf"
    save(src, out, state, store)
    handle.close()

    again = PdfDocument.open(out, store)
    rect = again.editable_images(0)[0].rect
    again.close()
    assert (rect.x, rect.y) == (pytest.approx(100), pytest.approx(100))
    assert (rect.w, rect.h) == (pytest.approx(300), pytest.approx(100))
