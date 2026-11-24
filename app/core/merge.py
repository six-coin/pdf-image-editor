"""把多张图压成一张。

纯函数：给一组同一页的 ``ImageObject``，返回新图的 ``image_id``、并集矩形和
一份报告，不碰撤销栈、不碰界面。

三条规则：

1. **分辨率取最高的那张**：像素密度 = 图片像素宽 / 它在页面上占的宽（pt）。
   密度最大的那张，每个像素在页面上占的面积最小；并集画布按这个密度取像素，
   其余图用双三次插值放大——只会放大，不会缩小（画布上限触发时除外）。
2. **按 z 序叠**：从下往上逐张合成，先画的在下、后画的在上。
3. **白底叠加**：画布先铺一层纯白不透明底，再把每张图按预乘 alpha 的
   source-over 叠上去。透明像素和并集空隙露出白底，最终结果没有 alpha 通道。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pymupdf

from app.core.imagestore import ImageStore
from app.models import ImageObject, Rect

# 画布上限：合并本身不限制选多少张，但一张四千万像素的 RGBA 源图已经要
# 160 MB，再大就会把内存吃光。超过时整体等比降低密度，报告里 ``scaled=True``。
MAX_PIXELS = 40_000_000
MAX_SIDE = 12_000
# 合成按横条推进：画布只留一份 uint8，工作内存与条高成正比。
_BAND_ROWS = 128


@dataclass(frozen=True)
class MergeReport:
    width: int
    height: int
    density: float
    scaled: bool

    def to_dict(self) -> dict[str, float | int | bool]:
        return {
            "width": self.width,
            "height": self.height,
            "density": round(self.density, 3),
            "scaled": self.scaled,
        }


def _cubic(distance: np.ndarray) -> np.ndarray:
    """Keys 双三次核，a = -0.5（Catmull-Rom）。"""
    x = np.abs(distance)
    near = 1.5 * x**3 - 2.5 * x**2 + 1.0
    far = -0.5 * x**3 + 2.5 * x**2 - 4.0 * x + 2.0
    return np.where(x <= 1.0, near, np.where(x < 2.0, far, 0.0))


def _weights(fractions: np.ndarray) -> np.ndarray:
    """四个抽头（-1/0/1/2）的权重，按行归一化，保证常数不被插值改掉。"""
    taps = np.stack([fractions + 1.0, fractions, 1.0 - fractions, 2.0 - fractions], axis=1).astype(
        np.float64
    )
    weight = _cubic(taps)
    weight /= weight.sum(axis=1, keepdims=True)
    return weight.astype(np.float32)


def _taps(out_size: int, in_size: int, start: int, stop: int) -> tuple[np.ndarray, np.ndarray]:
    """输出区间 ``[start, stop)`` 的源坐标与四抽头权重。像素中心对齐。"""
    scale = out_size / in_size
    centers = (np.arange(start, stop, dtype=np.float64) + 0.5) / scale - 0.5
    base = np.floor(centers).astype(np.int64)
    index = np.clip(base[:, None] + np.arange(-1, 3)[None, :], 0, in_size - 1)
    return index, _weights(centers - base)


def _resize_band(src: np.ndarray, out_w: int, out_h: int, row0: int, row1: int) -> np.ndarray:
    """把 ``src`` 缩放到 ``out_w × out_h``，只算 ``[row0, row1)`` 这几行。

    先竖后横：竖着抽四行累加，再横着抽四列累加。分条计算让工作内存只与条高
    有关，整页大图也不会一次分配几百 MB。
    """
    height, width, channels = src.shape
    if out_w == width and out_h == height:
        return src[row0:row1].astype(np.float32)

    y_index, y_weight = _taps(out_h, height, row0, row1)
    x_index, x_weight = _taps(out_w, width, 0, out_w)

    rows = row1 - row0
    band = np.zeros((rows, width, channels), np.float32)
    for tap in range(4):
        band += src[y_index[:, tap], :, :].astype(np.float32) * y_weight[:, tap][:, None, None]

    out = np.zeros((rows, out_w, channels), np.float32)
    for tap in range(4):
        out += band[:, x_index[:, tap], :] * x_weight[:, tap][None, :, None]

    np.clip(out, 0.0, 255.0, out=out)
    # 预乘空间的不变式：颜色分量不能大于 alpha，否则反预乘会溢出。
    out[..., :3] = np.minimum(out[..., :3], out[..., 3:4])
    return out


def _rgba(pix: pymupdf.Pixmap) -> np.ndarray:
    """统一成预乘 alpha 的 uint8 RGBA。

    带 alpha 的位图在 PyMuPDF 里本来就是预乘的；灰度复制成三通道，CMYK 转 RGB。
    """
    if pix.colorspace is None:
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
    elif pix.colorspace.n not in (1, 3):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    if pix.colorspace.n == 1 and not pix.alpha:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)

    components = pix.n
    raw = np.frombuffer(pix.samples, dtype=np.uint8)
    rows = raw[: pix.stride * pix.height].reshape(pix.height, pix.stride)
    rows = rows[:, : pix.width * components].reshape(pix.height, pix.width, components)

    if components == 4:
        return rows.copy()
    if components == 2:
        # 灰度 + alpha：样本同样是预乘的。
        rgba = np.empty((pix.height, pix.width, 4), np.uint8)
        rgba[..., 0] = rows[..., 0]
        rgba[..., 1] = rows[..., 0]
        rgba[..., 2] = rows[..., 0]
        rgba[..., 3] = rows[..., 1]
        return rgba
    if components == 3:
        rgba = np.empty((pix.height, pix.width, 4), np.uint8)
        rgba[..., :3] = rows
        rgba[..., 3] = 255
        return rgba
    rgba = np.empty((pix.height, pix.width, 4), np.uint8)
    rgba[..., 0] = rows[..., 0]
    rgba[..., 1] = rows[..., 0]
    rgba[..., 2] = rows[..., 0]
    rgba[..., 3] = 255
    return rgba


def _union(objects: list[ImageObject]) -> Rect:
    x0 = min(obj.rect.x for obj in objects)
    y0 = min(obj.rect.y for obj in objects)
    x1 = max(obj.rect.right for obj in objects)
    y1 = max(obj.rect.bottom for obj in objects)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def _density(obj: ImageObject, pix: pymupdf.Pixmap) -> float:
    """这张图在页面上每 pt 有多少像素。取两个方向的较大值——最细的那个方向
    决定「每个像素占多小」，也就是用户说的分辨率。"""
    return max(pix.width / obj.rect.w, pix.height / obj.rect.h)


def _clamped_size(width: int, height: int) -> tuple[int, int, float]:
    """超上限时整体等比缩小，返回 (宽, 高, 额外缩放系数)。"""
    if width <= MAX_SIDE and height <= MAX_SIDE and width * height <= MAX_PIXELS:
        return width, height, 1.0
    factor = min(MAX_SIDE / width, MAX_SIDE / height, (MAX_PIXELS / (width * height)) ** 0.5)
    return max(1, int(width * factor)), max(1, int(height * factor)), factor


def merge(objects: list[ImageObject], store: ImageStore) -> tuple[str, Rect, MergeReport] | None:
    """合并同一页上的多张图。少于两张、跨页或矩形退化时返回 ``None``。"""
    if len(objects) < 2:
        return None
    page = objects[0].page
    if any(obj.page != page or not obj.rect.is_valid() for obj in objects):
        return None

    pixmaps: list[tuple[ImageObject, pymupdf.Pixmap]] = []
    density = 0.0
    for obj in objects:
        try:
            pix = pymupdf.Pixmap(store.get(obj.image_id))
        except Exception:
            return None
        if pix.width <= 0 or pix.height <= 0:
            return None
        density = max(density, _density(obj, pix))
        pixmaps.append((obj, pix))
    if density <= 0.0:
        return None

    union = _union(objects)
    width = max(1, int(round(union.w * density)))
    height = max(1, int(round(union.h * density)))
    width, height, factor = _clamped_size(width, height)
    if factor != 1.0:
        density *= factor
        width = max(1, int(round(union.w * density)))
        height = max(1, int(round(union.h * density)))

    layers: list[tuple[np.ndarray, int, int, int, int]] = []
    for obj, pix in sorted(pixmaps, key=lambda item: item[0].z):
        # 目标边按页面坐标算，而不是「起点 + 宽」：相邻两张图共边时像素边界
        # 严丝合缝，不会出现 1px 的缝或叠。
        x0 = int(round((obj.rect.x - union.x) * density))
        x1 = int(round((obj.rect.right - union.x) * density))
        y0 = int(round((obj.rect.y - union.y) * density))
        y1 = int(round((obj.rect.bottom - union.y) * density))
        x0 = min(max(x0, 0), width)
        x1 = min(max(x1, 0), width)
        y0 = min(max(y0, 0), height)
        y1 = min(max(y1, 0), height)
        if x1 <= x0 or y1 <= y0:
            continue
        layers.append((_rgba(pix), x0, y0, x1 - x0, y1 - y0))
    if not layers:
        return None

    # 纯白实心底：结果必须是不透明的 RGB，透明像素和空隙都落到这层白上。
    canvas = np.full((height, width, 3), 255, np.uint8)
    for band_start in range(0, height, _BAND_ROWS):
        band_end = min(height, band_start + _BAND_ROWS)
        band = np.full((band_end - band_start, width, 3), 255.0, np.float32)
        for source, x0, y0, dest_w, dest_h in layers:
            top = max(band_start, y0)
            bottom = min(band_end, y0 + dest_h)
            if bottom <= top:
                continue
            piece = _resize_band(source, dest_w, dest_h, top - y0, bottom - y0)
            alpha = piece[..., 3:4] * (1.0 / 255.0)
            target = band[top - band_start : bottom - band_start, x0 : x0 + dest_w]
            # 预乘 alpha 的 source-over，目标是纯白不透明底：
            # src + dst × (1 − src_a)。结果仍是 straight RGB，不需要 alpha 通道。
            target[..., :3] = piece[..., :3] + target[..., :3] * (1.0 - alpha)
        np.clip(band, 0.0, 255.0, out=band)
        canvas[band_start:band_end] = np.rint(band).astype(np.uint8)

    # 最终产物恒为不透明 RGB：PNG 不带 alpha，后续无论压到什么底色上都一致。
    pix = pymupdf.Pixmap(pymupdf.csRGB, width, height, canvas.tobytes(), False)
    return store.put(pix.tobytes("png")), union, MergeReport(width, height, density, factor != 1.0)
