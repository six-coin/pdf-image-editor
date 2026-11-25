"""领域模型。

坐标一律是 PDF 点（pt），原点在页面左上角，y 向下。
这些结构不读写文件、不碰界面，只负责数据与形状。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def area(self) -> float:
        return self.w * self.h

    def is_valid(self) -> bool:
        return self.w > 0 and self.h > 0

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x <= self.right and self.y <= y <= self.bottom

    def translated(self, dx: float, dy: float) -> Rect:
        return Rect(self.x + dx, self.y + dy, self.w, self.h)

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.w, self.h]

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @classmethod
    def from_list(cls, values: list[float] | tuple[float, ...]) -> Rect:
        x, y, w, h = values
        return cls(float(x), float(y), float(w), float(h))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rect:
        return cls(float(data["x"]), float(data["y"]), float(data["w"]), float(data["h"]))


@dataclass
class ImageObject:
    """画布上的一张图。

    ``rect`` 是当前显示位置，``src_rect`` 是它在原文档里的原始放置位置。
    保存时按 ``src_rect`` 做 redaction、按 ``rect`` 重新插入——两者必须分开存，
    否则"移动一张图"没法表达成"在原位删除 + 在新位插入"。``src_page`` 记的是
    ``src_rect`` 属于哪一页：跨页拖动后它不会跟着 ``page`` 变。
    """

    id: str
    page: int
    rect: Rect
    image_id: str
    src_xref: int | None = None
    src_rect: Rect | None = None
    # 原图在哪一页。跨页拖动后 page 变了、src_page 不变，保存时才知道去哪儿擦。
    src_page: int | None = None
    z: int = 10
    rotation: int = 0
    opacity: float = 1.0

    @property
    def kind(self) -> str:
        return "image"

    def clone(self) -> ImageObject:
        return replace(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": "image",
            "page": self.page,
            "x": self.rect.x,
            "y": self.rect.y,
            "w": self.rect.w,
            "h": self.rect.h,
            "z": self.z,
            "rotation": self.rotation,
            "image": self.image_id,
        }


@dataclass(frozen=True)
class TextRun:
    """一段文字 + 一种字体。文本框里可以有多段，各用各的字体。"""

    text: str
    font: str = "msyh"

    def to_list(self) -> list[str]:
        return [self.text, self.font]

    @classmethod
    def from_any(cls, data: Any) -> TextRun:
        if isinstance(data, dict):
            return cls(str(data.get("text", "")), str(data.get("font", "msyh")))
        if isinstance(data, (list, tuple)) and len(data) >= 2:
            return cls(str(data[0]), str(data[1]))
        return cls(str(data or ""), "msyh")


@dataclass
class TextObject:
    """画布上的一个文本框。

    ``rect.w`` 是用户能拖的宽度，``rect.h`` 永远由排版算出——它跟着内容长高，
    不给手柄也不接受外部写入。字号用 px（与 Edge 批注一致，落盘时 ×0.75 变 pt），
    ``line_height`` 是字号的倍数。
    """

    id: str
    page: int
    rect: Rect
    runs: list[TextRun] = field(default_factory=list)
    size_px: int = 14
    line_height: float = 1.15
    color: str = "blue"
    z: int = 10

    @property
    def kind(self) -> str:
        return "text"

    def clone(self) -> TextObject:
        return replace(self, runs=[TextRun(run.text, run.font) for run in self.runs])

    def text(self) -> str:
        return "".join(run.text for run in self.runs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": "text",
            "page": self.page,
            "x": self.rect.x,
            "y": self.rect.y,
            "w": self.rect.w,
            "h": self.rect.h,
            "z": self.z,
            "size": self.size_px,
            "line_height": self.line_height,
            "color": self.color,
            "runs": [run.to_list() for run in self.runs],
        }

    def to_pdf_dict(self) -> dict[str, Any]:
        """写进 PDF 的紧凑形式。键名短一点，一页几十个框时省下的不是一点。"""
        return {
            "k": "text",
            "id": self.id,
            "x": round(self.rect.x, 3),
            "y": round(self.rect.y, 3),
            "w": round(self.rect.w, 3),
            "h": round(self.rect.h, 3),
            "z": self.z,
            "size": self.size_px,
            "lh": self.line_height,
            "color": self.color,
            "runs": [run.to_list() for run in self.runs],
        }

    @classmethod
    def from_pdf_dict(cls, data: dict[str, Any], page: int) -> TextObject:
        runs = [TextRun.from_any(item) for item in data.get("runs") or []]
        return cls(
            id=str(data.get("id") or ""),
            page=page,
            rect=Rect(
                float(data.get("x", 0.0)),
                float(data.get("y", 0.0)),
                float(data.get("w", 100.0)),
                float(data.get("h", 20.0)),
            ),
            runs=runs,
            size_px=int(data.get("size", 14)),
            line_height=float(data.get("lh", 1.15)),
            color=str(data.get("color", "blue")),
            z=int(data.get("z", 10)),
        )


@dataclass
class HighlightObject:
    """一条横向荧光带。宽高都定死，只能挪位置。"""

    id: str
    page: int
    rect: Rect
    color: str = "yellow"
    z: int = 10

    @property
    def kind(self) -> str:
        return "highlight"

    def clone(self) -> HighlightObject:
        return replace(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": "highlight",
            "page": self.page,
            "x": self.rect.x,
            "y": self.rect.y,
            "w": self.rect.w,
            "h": self.rect.h,
            "z": self.z,
            "color": self.color,
        }

    def to_pdf_dict(self) -> dict[str, Any]:
        return {
            "k": "hl",
            "id": self.id,
            "x": round(self.rect.x, 3),
            "y": round(self.rect.y, 3),
            "w": round(self.rect.w, 3),
            "h": round(self.rect.h, 3),
            "z": self.z,
            "color": self.color,
        }

    @classmethod
    def from_pdf_dict(cls, data: dict[str, Any], page: int) -> HighlightObject:
        return cls(
            id=str(data.get("id") or ""),
            page=page,
            rect=Rect(
                float(data.get("x", 0.0)),
                float(data.get("y", 0.0)),
                float(data.get("w", 100.0)),
                float(data.get("h", 11.25)),
            ),
            color=str(data.get("color", "yellow")),
            z=int(data.get("z", 10)),
        )


CanvasObject = ImageObject | TextObject | HighlightObject


@dataclass(frozen=True)
class PageInfo:
    index: int
    width: float
    height: float
    has_text: bool = False
    locked_images: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "w": self.width,
            "h": self.height,
            "has_text": self.has_text,
            "locked": self.locked_images,
        }


@dataclass
class DocumentState:
    """内存里的文档。界面只读它，撤销栈只改它。"""

    path: Path | None = None
    pages: list[PageInfo] = field(default_factory=list)
    objects: list[CanvasObject] = field(default_factory=list)
    selection: list[str] = field(default_factory=list)
    # 被删掉的原图位置。对象没了，但它在 PDF 里还占着地方，保存时仍要 redaction。
    removed: dict[int, list[Rect]] = field(default_factory=dict)
    # 已经装载进模型的页。保存时只能动这些页：没装载过的页在模型里没有任何对象，
    # 擦掉它的覆盖层就再也画不回来了（保存一次少一页的文字）。
    # ``None`` 表示调用方不跟踪装载状态，按「全都装载过」处理。
    loaded: set[int] | None = None

    def mark_removed(self, page: int, rect: Rect | None) -> None:
        if rect is None:
            return
        bucket = self.removed.setdefault(page, [])
        if rect not in bucket:
            bucket.append(rect)

    def find(self, object_id: str) -> CanvasObject | None:
        for obj in self.objects:
            if obj.id == object_id:
                return obj
        return None

    def objects_on(self, page: int) -> list[CanvasObject]:
        return [o for o in self.objects if o.page == page]

    def images_on(self, page: int) -> list[ImageObject]:
        return [o for o in self.objects if o.page == page and isinstance(o, ImageObject)]

    def overlays_on(self, page: int) -> list[TextObject | HighlightObject]:
        """这一页的文本框与荧光带，按 z 升序。"""
        items = [o for o in self.objects if o.page == page and not isinstance(o, ImageObject)]
        return sorted(items, key=lambda o: o.z)

    def sorted_objects(self) -> list[CanvasObject]:
        """按 z 升序；同 z 保持列表原有次序（稳定排序）。"""
        return sorted(self.objects, key=lambda o: o.z)

    def next_z(self, page: int) -> int:
        existing = [o.z for o in self.objects if o.page == page]
        return (max(existing) + 1) if existing else 10

    def upsert(self, objects: list[CanvasObject]) -> None:
        """按 id 覆盖；不存在则追加。幂等——重复调用结果相同。"""
        index = {o.id: i for i, o in enumerate(self.objects)}
        for obj in objects:
            slot = index.get(obj.id)
            if slot is None:
                index[obj.id] = len(self.objects)
                self.objects.append(obj.clone())
            else:
                self.objects[slot] = obj.clone()

    def drop(self, object_ids: list[str]) -> None:
        doomed = set(object_ids)
        self.objects = [o for o in self.objects if o.id not in doomed]
        self.selection = [s for s in self.selection if s not in doomed]

    def replace_all(self, objects: list[CanvasObject]) -> None:
        self.objects = [o.clone() for o in objects]

    def clone_objects(self) -> list[CanvasObject]:
        return [o.clone() for o in self.objects]

    def renormalize(self, page: int) -> None:
        """把某一页的 z 重新编号成 10、11、12…，避免结构编辑后出现重复层级。"""
        items = [o for o in self.objects if o.page == page]
        items.sort(key=lambda o: o.z)
        for offset, obj in enumerate(items):
            obj.z = 10 + offset
