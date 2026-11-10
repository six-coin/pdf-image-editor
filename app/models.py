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
    否则"移动一张图"没法表达成"在原位删除 + 在新位插入"。
    """

    id: str
    page: int
    rect: Rect
    image_id: str
    src_xref: int | None = None
    src_rect: Rect | None = None
    z: int = 10
    rotation: int = 0
    opacity: float = 1.0

    def clone(self) -> ImageObject:
        return replace(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
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
    objects: list[ImageObject] = field(default_factory=list)
    selection: list[str] = field(default_factory=list)
    # 被删掉的原图位置。对象没了，但它在 PDF 里还占着地方，保存时仍要 redaction。
    removed: dict[int, list[Rect]] = field(default_factory=dict)

    def mark_removed(self, page: int, rect: Rect | None) -> None:
        if rect is None:
            return
        bucket = self.removed.setdefault(page, [])
        if rect not in bucket:
            bucket.append(rect)

    def find(self, object_id: str) -> ImageObject | None:
        for obj in self.objects:
            if obj.id == object_id:
                return obj
        return None

    def objects_on(self, page: int) -> list[ImageObject]:
        return [o for o in self.objects if o.page == page]

    def sorted_objects(self) -> list[ImageObject]:
        """按 z 升序；同 z 保持列表原有次序（稳定排序）。"""
        return sorted(self.objects, key=lambda o: o.z)

    def next_z(self, page: int) -> int:
        existing = [o.z for o in self.objects if o.page == page]
        return (max(existing) + 1) if existing else 10

    def upsert(self, objects: list[ImageObject]) -> None:
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

    def replace_all(self, objects: list[ImageObject]) -> None:
        self.objects = [o.clone() for o in objects]

    def clone_objects(self) -> list[ImageObject]:
        return [o.clone() for o in self.objects]

    def renormalize(self, page: int) -> None:
        """把某一页的 z 重新编号成 10、11、12…，避免结构编辑后出现重复层级。"""
        items = [o for o in self.objects if o.page == page]
        items.sort(key=lambda o: o.z)
        for offset, obj in enumerate(items):
            obj.z = 10 + offset
