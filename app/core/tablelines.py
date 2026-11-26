"""表格框线拉直。

输入是一张图片（PNG/JPEG 字节），输出是同样尺寸、框线被拉成严格水平/竖直的
PNG。只处理「长、细、近轴对齐」的表格线，不碰文字：

1. 长游程分离横/竖线：只保留原游程，不做膨胀，端点才不会被撑出去。
2. 游程连通域 + 可靠线支撑：贯穿 75% 图宽/高的线直接收；其余线两端都搭在
   可靠线（≥8% 图宽/高）上才收。手写长横线两端不搭线，不会被当成表格线。
3. 逐列墨迹重心拟合中心线；线宽固定 3px，不做任何宽度统计。
4. 只擦每条线自己的窄带（逐列跟随原中心），重绘纯黑线芯、按像素栅格对齐。
5. 交叉口按 corner / T 型收放端点：corner 延到对面线的外像素边，
   T 型只收到对面线的中心线，避免在横线外侧多出一截。

倾斜超过约 0.5° 的图不在保证范围内：强行拉平会让线和文字错位。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pymupdf

_BLACK = np.array([0.0, 0.0, 0.0], dtype=np.float32)
_THICKNESS = 3
_MAX_LINE_THICKNESS = 14
_MAX_FIT_RMS = 1.5
_MAX_FIT_DEVIATION = 5.0
_MAX_THICKNESS_SPREAD = 0.35
_SEED_RATIO = 0.75
_RELIABLE_RATIO = 0.08
# 一条线至少要有这么长才算表格线。短于它的笔画一律不碰：手写批注里
# 几十像素的横竖线太多，按「线」处理只会把字迹拉成栅栏。设置里可调
# （20–340），默认值由 settings.TABLE_MIN_SPAN_DEFAULT 决定。
DEFAULT_MIN_SPAN = 170
# 端点落在另一条线（或它的端点）上就算接上了。扫描件线头常多出几像素。
_CONNECT_TOL = 9.0


@dataclass(frozen=True)
class TableLinesReport:
    """一次框线处理的结果。

    ``thickness`` 固定是 3（像素），保留在报告里只是给界面提示用。
    """

    horizontal: int = 0
    vertical: int = 0
    thickness: int = 0
    applied: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "horizontal": self.horizontal,
            "vertical": self.vertical,
            "thickness": self.thickness,
            "applied": self.applied,
            "reason": self.reason,
        }


def straighten(data: bytes, min_span: int = DEFAULT_MIN_SPAN) -> tuple[bytes, TableLinesReport]:
    """把图片里的表格框线拉直，返回 ``(新图片字节, 报告)``。

    ``min_span`` 是最短表格线长度（px）；短于它的笔画不会被当成线。
    识别不到足够的表格线时原样返回，``applied`` 为 ``False``；图片本身解不开
    会抛 ``ValueError``，由调用方转成界面提示。
    """
    short_min = max(1, int(min_span))
    array, width, height = _load_rgb(data)
    gray = array.astype(np.float32).mean(axis=2)
    threshold = _otsu(gray)
    # 白底上只有几条细黑线时，Otsu 可能把阈值压到 0；给一个下限，
    # 免得浅灰的框线整条都进不了掩膜。
    if float(np.median(gray)) > 200:
        threshold = max(threshold, 96)
    ink = gray <= threshold
    # 线芯掩膜：只用深色像素算重心，抗锯齿边不参与。
    core = gray <= min(threshold, 100)

    kernel = max(24, int(round(0.02 * max(width, height))))
    horizontal_mask = _filter_runs(ink, kernel, 1)
    vertical_mask = _filter_runs(ink, kernel, 0)

    hcands = _candidates(ink, core, horizontal_mask, "h", width, height)
    vcands = _candidates(ink, core, vertical_mask, "v", width, height)
    accepted_h, accepted_v = _accept(hcands, vcands, width, height, short_min)
    if len(accepted_h) + len(accepted_v) < 3:
        return data, TableLinesReport(reason="no_lines")

    thickness = _THICKNESS

    # 擦除按「段」走（跟着原始抖动），绘制按「条」走（同一行/列被竖线切开的
    # 段合并成一条，避免在切口处差出一个像素的台阶）。
    draw_h = _merge(accepted_h, "h")
    draw_v = _merge(accepted_v, "v")

    work = array.astype(np.float32)
    _erase(work, gray, accepted_h, accepted_v, thickness, width, height)
    _draw(work, draw_h, draw_v, thickness, width, height)

    out = np.clip(work, 0, 255).astype(np.uint8)
    pix = pymupdf.Pixmap(
        pymupdf.csRGB,
        width,
        height,
        np.ascontiguousarray(out).tobytes(),
        False,
    )
    return pix.tobytes("png"), TableLinesReport(
        horizontal=len(draw_h),
        vertical=len(draw_v),
        thickness=thickness,
        applied=True,
        reason="ok",
    )


# ---------- 读图 ----------


def _load_rgb(data: bytes) -> tuple[np.ndarray, int, int]:
    pix = pymupdf.Pixmap(data)
    if pix.colorspace is not None and pix.colorspace.n == 4 and not pix.alpha:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    width, height, channels = pix.width, pix.height, pix.n
    stride = pix.stride
    raw = np.frombuffer(pix.samples, dtype=np.uint8)
    arr = raw.reshape(height, stride)[:, : width * channels].reshape(height, width, channels)

    if channels == 1:
        return np.repeat(arr, 3, axis=2), width, height
    if channels == 2:
        alpha = arr[:, :, 1:2].astype(np.float32) / 255.0
        gray = arr[:, :, :1].astype(np.float32)
        merged = (gray * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)
        return np.repeat(merged, 3, axis=2), width, height
    if channels == 3:
        return arr.copy(), width, height
    if channels == 4:
        alpha = arr[:, :, 3:4].astype(np.float32) / 255.0
        rgb = arr[:, :, :3].astype(np.float32) * alpha + 255.0 * (1.0 - alpha)
        return rgb.astype(np.uint8), width, height
    raise ValueError(f"unsupported image with {channels} channels")


def _otsu(gray: np.ndarray) -> int:
    hist = np.bincount(gray.astype(np.uint8).ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    sum_all = float(np.dot(np.arange(256), hist))
    weight_b = 0.0
    sum_b = 0.0
    best = -1.0
    threshold = 128
    for t in range(256):
        weight_b += hist[t]
        if weight_b == 0:
            continue
        weight_f = total - weight_b
        if weight_f == 0:
            break
        sum_b += t * hist[t]
        mean_b = sum_b / weight_b
        mean_f = (sum_all - sum_b) / weight_f
        variance = weight_b * weight_f * (mean_b - mean_f) ** 2
        if variance > best:
            best = variance
            threshold = t
    return threshold


# ---------- 找线 ----------


def _filter_runs(mask: np.ndarray, min_len: int, axis: int) -> np.ndarray:
    """保留长度 >= min_len 的连续段，且保留原段两端（不做膨胀）。"""
    view = mask if axis == 1 else mask.T
    out = np.zeros_like(view)
    for i in range(view.shape[0]):
        idx = np.flatnonzero(view[i])
        if idx.size == 0:
            continue
        breaks = np.flatnonzero(np.diff(idx) > 1)
        starts = np.concatenate(([idx[0]], idx[breaks + 1]))
        ends = np.concatenate((idx[breaks], [idx[-1]]))
        for start, end in zip(starts.tolist(), ends.tolist(), strict=True):
            if end - start + 1 >= min_len:
                out[i, start : end + 1] = True
    return out if axis == 1 else out.T


def _components(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """游程连通域，返回 ``(x0, x1, y0, y1)``。"""
    parent: list[int] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    prev: list[tuple[int, int, int]] = []
    runs: list[tuple[int, int, int, int]] = []
    for y in range(mask.shape[0]):
        idx = np.flatnonzero(mask[y])
        current: list[tuple[int, int, int]] = []
        if idx.size:
            breaks = np.flatnonzero(np.diff(idx) > 1)
            starts = np.concatenate(([idx[0]], idx[breaks + 1]))
            ends = np.concatenate((idx[breaks], [idx[-1]]))
            for start, end in zip(starts.tolist(), ends.tolist(), strict=True):
                rid = len(parent)
                parent.append(rid)
                runs.append((y, start, end, rid))
                current.append((start, end, rid))
        j = 0
        for start, end, rid in current:
            while j < len(prev) and prev[j][1] < start - 1:
                j += 1
            k = j
            while k < len(prev) and prev[k][0] <= end + 1:
                union(rid, prev[k][2])
                k += 1
        prev = current

    groups: dict[int, list[int]] = {}
    for y, start, end, rid in runs:
        root = find(rid)
        box = groups.get(root)
        if box is None:
            groups[root] = [start, end, y, y]
        else:
            box[0] = min(box[0], start)
            box[1] = max(box[1], end)
            box[2] = min(box[2], y)
            box[3] = max(box[3], y)
    return [tuple(box) for box in groups.values()]


def _candidates(
    ink: np.ndarray,
    core: np.ndarray,
    mask: np.ndarray,
    axis: str,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for x0, x1, y0, y1 in _components(mask):
        if axis == "h":
            if x1 - x0 + 1 < 24 or y1 - y0 + 1 > _MAX_LINE_THICKNESS:
                continue
            item = _pick_measure(_measure_h(core, x0, x1, y0, y1), _measure_h(ink, x0, x1, y0, y1))
        else:
            if y1 - y0 + 1 < 24 or x1 - x0 + 1 > _MAX_LINE_THICKNESS:
                continue
            item = _pick_measure(_measure_v(core, x0, x1, y0, y1), _measure_v(ink, x0, x1, y0, y1))
        if item is not None:
            item["cid"] = f"{axis}{len(result)}"
            result.append(item)
    return result


def _pick_measure(
    core_item: dict[str, Any] | None, ink_item: dict[str, Any] | None
) -> dict[str, Any] | None:
    """线芯与整条墨迹各量一次，挑更靠谱的那份。

    线芯掩膜只留最深的像素，浅灰线会断断续续，量出来的相对厚度波动虚高；
    整条墨迹更连续，但抗锯齿边会把中心线稍微带偏。优先用通过几何检查的
    那份：线芯合格就用线芯，否则退到墨迹；两份都不合格时留波动小的那份，
    交给后面的 ``_good`` 淘汰。
    """
    if core_item is None:
        return ink_item
    if ink_item is None:
        return core_item
    if _good(core_item):
        return core_item
    if _good(ink_item):
        return ink_item
    return core_item if core_item["spread"] <= ink_item["spread"] else ink_item


def _measure_h(ink: np.ndarray, x0: int, x1: int, y0: int, y1: int) -> dict[str, Any] | None:
    ys = np.arange(max(0, y0 - 1), min(ink.shape[0], y1 + 2))
    band = ink[ys[0] : ys[-1] + 1, x0 : x1 + 1]
    counts = band.sum(axis=0).astype(np.float64)
    sums = (band * ys[:, None]).sum(axis=0)
    valid = (counts > 0) & (counts <= _MAX_LINE_THICKNESS)
    if valid.sum() < 8:
        return None
    xs = np.arange(x0, x1 + 1, dtype=np.float64)
    centers = sums[valid] / counts[valid]
    centers_full = np.full(counts.shape, np.nan)
    centers_full[valid] = centers
    slope, intercept = np.polyfit(xs[valid], centers, 1)
    residual = centers - (slope * xs[valid] + intercept)
    keep = np.abs(residual - np.median(residual)) <= 1.5
    if keep.sum() >= 6:
        slope, intercept = np.polyfit(xs[valid][keep], centers[keep], 1)
        residual = centers[keep] - (slope * xs[valid][keep] + intercept)
    # 厚度波动只看参与拟合的列：贴着线的字会把个别列的墨迹算多，
    # 拿全部列算方差会把一条 2px 的细线误判成「粗细不均的笔画」。
    spread_counts = counts[valid][keep] if keep.sum() >= 6 else counts[valid]
    return {
        "axis": "h",
        "x0": x0,
        "x1": x1,
        "y0": y0,
        "y1": y1,
        "span": x1 - x0 + 1,
        "center": float(slope * ((x0 + x1) / 2.0) + intercept),
        "k": float(slope),
        "b": float(intercept),
        "rms": float(np.sqrt((residual**2).mean())),
        "max": float(np.abs(residual).max()),
        "spread": float(np.std(spread_counts) / max(1e-6, np.mean(spread_counts))),
        "centers": centers_full,
    }


def _measure_v(ink: np.ndarray, x0: int, x1: int, y0: int, y1: int) -> dict[str, Any] | None:
    xs = np.arange(max(0, x0 - 1), min(ink.shape[1], x1 + 2))
    band = ink[y0 : y1 + 1, xs[0] : xs[-1] + 1]
    counts = band.sum(axis=1).astype(np.float64)
    sums = (band * xs[None, :]).sum(axis=1)
    valid = (counts > 0) & (counts <= _MAX_LINE_THICKNESS)
    if valid.sum() < 8:
        return None
    ys = np.arange(y0, y1 + 1, dtype=np.float64)
    centers = sums[valid] / counts[valid]
    centers_full = np.full(counts.shape, np.nan)
    centers_full[valid] = centers
    slope, intercept = np.polyfit(ys[valid], centers, 1)
    residual = centers - (slope * ys[valid] + intercept)
    keep = np.abs(residual - np.median(residual)) <= 1.5
    if keep.sum() >= 6:
        slope, intercept = np.polyfit(ys[valid][keep], centers[keep], 1)
        residual = centers[keep] - (slope * ys[valid][keep] + intercept)
    spread_counts = counts[valid][keep] if keep.sum() >= 6 else counts[valid]
    return {
        "axis": "v",
        "x0": x0,
        "x1": x1,
        "y0": y0,
        "y1": y1,
        "span": y1 - y0 + 1,
        "center": float(slope * ((y0 + y1) / 2.0) + intercept),
        "k": float(slope),
        "b": float(intercept),
        "rms": float(np.sqrt((residual**2).mean())),
        "max": float(np.abs(residual).max()),
        "spread": float(np.std(spread_counts) / max(1e-6, np.mean(spread_counts))),
        "centers": centers_full,
    }


def _good(item: dict[str, Any]) -> bool:
    return (
        item["rms"] <= _MAX_FIT_RMS
        and item["max"] <= _MAX_FIT_DEVIATION
        and item["spread"] <= _MAX_THICKNESS_SPREAD
    )


def _h_support(x_end: float, y_end: float, verticals: list[dict[str, Any]], width: int) -> bool:
    if x_end <= 2 or x_end >= width - 3:
        return True
    for line in verticals:
        if abs(line["center"] - x_end) <= 6 and line["y0"] - 6 <= y_end <= line["y1"] + 6:
            return True
    return False


def _v_support(y_end: float, x_end: float, horizontals: list[dict[str, Any]], height: int) -> bool:
    if y_end <= 2 or y_end >= height - 3:
        return True
    for line in horizontals:
        if abs(line["center"] - y_end) <= 6 and line["x0"] - 6 <= x_end <= line["x1"] + 6:
            return True
    return False


def _accept(
    hcands: list[dict[str, Any]],
    vcands: list[dict[str, Any]],
    width: int,
    height: int,
    short_min: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """认线：长线直接收，短线必须两端都搭在「可靠线」上。

    可靠线 = 长度至少占图宽/高 8% 且几何合格的候选。它不一定被最终接受，
    但足以当短线的支撑。这样表格不必铺满整张图，也不会让手写笔画互相支撑。

    收下的线还要再筛一遍：两端都不与任何垂直线形成 corner / 丁字口的，
    属于孤立笔画（只是从别的线上横穿而过不算接上），一律不要。
    """
    reliable_h = [
        c for c in hcands if _good(c) and c["span"] >= max(short_min, _RELIABLE_RATIO * width)
    ]
    reliable_v = [
        c for c in vcands if _good(c) and c["span"] >= max(short_min, _RELIABLE_RATIO * height)
    ]

    accepted_h: list[dict[str, Any]] = []
    for item in hcands:
        if not _good(item) or item["span"] < short_min:
            continue
        if item["span"] >= _SEED_RATIO * width:
            accepted_h.append(item)
            continue
        left = _h_support(item["x0"], item["k"] * item["x0"] + item["b"], reliable_v, width)
        right = _h_support(item["x1"], item["k"] * item["x1"] + item["b"], reliable_v, width)
        if left and right:
            accepted_h.append(item)

    accepted_v: list[dict[str, Any]] = []
    for item in vcands:
        if not _good(item) or item["span"] < short_min:
            continue
        if item["span"] >= _SEED_RATIO * height:
            accepted_v.append(item)
            continue
        top = _v_support(item["y0"], item["k"] * item["y0"] + item["b"], reliable_h, height)
        bottom = _v_support(item["y1"], item["k"] * item["y1"] + item["b"], reliable_h, height)
        if top and bottom:
            accepted_v.append(item)

    return _drop_isolated(_dedupe(accepted_h), _dedupe(accepted_v))


def _h_connected(item: dict[str, Any], verticals: list[dict[str, Any]]) -> bool:
    """横线的任一端点落在某条竖线上（含端点）就算接上。"""
    for x in (item["x0"], item["x1"]):
        y = item["k"] * x + item["b"]
        for other in verticals:
            if abs(other["k"] * y + other["b"] - x) > _CONNECT_TOL:
                continue
            if other["y0"] - _CONNECT_TOL <= y <= other["y1"] + _CONNECT_TOL:
                return True
    return False


def _v_connected(item: dict[str, Any], horizontals: list[dict[str, Any]]) -> bool:
    """竖线的任一端点落在某条横线上（含端点）就算接上。"""
    for y in (item["y0"], item["y1"]):
        x = item["k"] * y + item["b"]
        for other in horizontals:
            if abs(other["k"] * x + other["b"] - y) > _CONNECT_TOL:
                continue
            if other["x0"] - _CONNECT_TOL <= x <= other["x1"] + _CONNECT_TOL:
                return True
    return False


def _drop_isolated(
    horizontals: list[dict[str, Any]], verticals: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """去掉两端都没有 corner / 丁字口的线。

    ``_h_connected`` 只看端点：一条横线从竖线中间穿过去（十字交叉）时，
    两个端点都不在竖线上，按规则不算接上——手写笔画常常正好压在表格线上。
    """
    kept_h = [item for item in horizontals if _h_connected(item, verticals)]
    kept_v = [item for item in verticals if _v_connected(item, horizontals)]
    return kept_h, kept_v


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(items, key=lambda c: c["span"], reverse=True)
    kept: list[dict[str, Any]] = []
    for item in ordered:
        duplicate = False
        for other in kept:
            if abs(item["center"] - other["center"]) > 2:
                continue
            lo = max(item["x0"], other["x0"])
            hi = min(item["x1"], other["x1"])
            if hi - lo > 0.5 * min(item["span"], other["span"]):
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return kept


def _merge(items: list[dict[str, Any]], axis: str) -> list[dict[str, Any]]:
    """把同一条线被垂直方向的线切开的段并成一条。

    只合并「中心差 <= 2px、端点间隙 <= 8px」的段；中心取按长度加权的平均，
    这样切口两侧不会一个在 179.5、一个在 180.5，连起来是个台阶。
    """
    ordered = sorted(items, key=lambda c: (c["center"], c["x0"] if axis == "h" else c["y0"]))
    groups: list[dict[str, Any]] = []
    for item in ordered:
        target = None
        for group in groups:
            same_center = abs(item["center"] - group["center"]) <= 2
            if axis == "h":
                adjacent = item["x0"] <= group["x1"] + 8 and item["x1"] >= group["x0"] - 8
            else:
                adjacent = item["y0"] <= group["y1"] + 8 and item["y1"] >= group["y0"] - 8
            if same_center and adjacent:
                target = group
                break
        if target is None:
            groups.append(
                {
                    "axis": axis,
                    "x0": item["x0"],
                    "x1": item["x1"],
                    "y0": item["y0"],
                    "y1": item["y1"],
                    "center": item["center"],
                    "span": item["span"],
                    "_weight": float(item["span"]),
                }
            )
            continue
        weight = float(item["span"])
        total = target["_weight"] + weight
        target["center"] = (target["center"] * target["_weight"] + item["center"] * weight) / total
        target["_weight"] = total
        target["x0"] = min(target["x0"], item["x0"])
        target["x1"] = max(target["x1"], item["x1"])
        target["y0"] = min(target["y0"], item["y0"])
        target["y1"] = max(target["y1"], item["y1"])
        target["span"] = (
            target["x1"] - target["x0"] + 1 if axis == "h" else target["y1"] - target["y0"] + 1
        )
    for group in groups:
        group.pop("_weight", None)
    return groups


# ---------- 擦与画 ----------


def _erase(
    work: np.ndarray,
    gray: np.ndarray,
    horizontals: list[dict[str, Any]],
    verticals: list[dict[str, Any]],
    thickness: int,
    width: int,
    height: int,
) -> None:
    """只擦每条线自己的窄带，逐列跟着原始中心走，避免削掉贴线的字。"""
    paper = np.median(work[gray > 180].reshape(-1, 3), axis=0).astype(np.float32)
    half = thickness / 2.0 + 2.0
    for line in horizontals:
        xs = np.arange(line["x0"], line["x1"] + 1)
        centers = np.where(
            np.isnan(line["centers"]),
            line["k"] * xs + line["b"],
            line["centers"],
        )
        top = np.floor(centers - half).astype(int)
        bottom = np.ceil(centers + half).astype(int)
        for x, y0, y1 in zip(xs.tolist(), top.tolist(), bottom.tolist(), strict=True):
            work[max(0, y0) : min(height, y1 + 1), x] = paper
    for line in verticals:
        ys = np.arange(line["y0"], line["y1"] + 1)
        centers = np.where(
            np.isnan(line["centers"]),
            line["k"] * ys + line["b"],
            line["centers"],
        )
        left = np.floor(centers - half).astype(int)
        right = np.ceil(centers + half).astype(int)
        for y, x0, x1 in zip(ys.tolist(), left.tolist(), right.tolist(), strict=True):
            work[y, max(0, x0) : min(width, x1 + 1)] = paper


def _snap(center: float, thickness: int) -> float:
    """把线心对到像素栅格上：奇数宽对半像素，偶数宽对整像素。

    这样 W 条像素正好整行覆盖，不会因为亚像素位置看起来时粗时细，
    二次处理时也不会把线挪动半像素。
    """
    # 3px 线量出来的是像素索引的均值（落在中间那一行），几何中心要再偏半格；
    # 但 579.988 这种「刚好差一点到整数」的噪声如果直接 floor 会整整挪一格，
    # 所以先判断它是不是已经落在某个整数行上。
    if thickness % 2:
        if abs(center - round(center)) < 0.2:
            return float(round(center) + 0.5)
        return float(np.floor(center) + 0.5)
    if abs(center - round(center)) < 0.2:
        return float(round(center))
    return float(np.floor(center + 0.5))


def _draw(
    work: np.ndarray,
    horizontals: list[dict[str, Any]],
    verticals: list[dict[str, Any]],
    thickness: int,
    width: int,
    height: int,
) -> None:
    """画严格水平/竖直的线；交叉口按 corner / T 型分别收放端点。"""
    for line in horizontals:
        line["center"] = _snap(line["center"], thickness)
    for line in verticals:
        line["center"] = _snap(line["center"], thickness)

    # 交叉口分两种：
    # - corner：两条线都在这里结束，端点直接对到对面线的外像素边；
    # - T 型：一条线穿过、另一条在这里结束，结束的那条只收到对面线的中心线。
    # 判定放宽到 9px：扫描件里线头多出几像素很常见，只要在这个范围内都当作
    # 同一个交叉口，按规则把多余的线头收掉。
    join_tol = 9.0
    end_tol = thickness / 2.0 + 1.0

    def ends_at(center: float, lo: int, hi: int) -> bool:
        return abs(center - lo) <= end_tol or abs(center - hi) <= end_tol

    for line in horizontals:
        line["draw_x0"], line["draw_x1"] = line["x0"], line["x1"]
        for other in verticals:
            if not (other["y0"] - 2 <= line["center"] <= other["y1"] + 2):
                continue
            corner = ends_at(line["center"], other["y0"], other["y1"])
            if abs(other["center"] - line["x0"]) <= join_tol:
                if corner:
                    line["draw_x0"] = int(np.floor(other["center"] - thickness / 2.0))
                else:
                    line["draw_x0"] = int(round(other["center"]))
            if abs(other["center"] - line["x1"]) <= join_tol:
                if corner:
                    line["draw_x1"] = int(np.ceil(other["center"] + thickness / 2.0)) - 1
                else:
                    line["draw_x1"] = int(round(other["center"]))
        line["draw_x0"] = max(0, line["draw_x0"])
        line["draw_x1"] = min(width - 1, line["draw_x1"])
        if line["draw_x0"] >= line["draw_x1"]:
            line["draw_x0"], line["draw_x1"] = line["x0"], line["x1"]

    for line in verticals:
        line["draw_y0"], line["draw_y1"] = line["y0"], line["y1"]
        for other in horizontals:
            if not (other["x0"] - 2 <= line["center"] <= other["x1"] + 2):
                continue
            corner = ends_at(line["center"], other["x0"], other["x1"])
            if abs(other["center"] - line["y0"]) <= join_tol:
                if corner:
                    line["draw_y0"] = int(np.floor(other["center"] - thickness / 2.0))
                else:
                    line["draw_y0"] = int(round(other["center"]))
            if abs(other["center"] - line["y1"]) <= join_tol:
                if corner:
                    line["draw_y1"] = int(np.ceil(other["center"] + thickness / 2.0)) - 1
                else:
                    line["draw_y1"] = int(round(other["center"]))
        line["draw_y0"] = max(0, line["draw_y0"])
        line["draw_y1"] = min(height - 1, line["draw_y1"])
        if line["draw_y0"] >= line["draw_y1"]:
            line["draw_y0"], line["draw_y1"] = line["y0"], line["y1"]

    half = thickness / 2.0
    for line in horizontals:
        xs = np.arange(line["draw_x0"], line["draw_x1"] + 1)
        top = line["center"] - half
        bottom = line["center"] + half
        for y in range(int(np.floor(top)), int(np.ceil(bottom))):
            if y < 0 or y >= height:
                continue
            coverage = min(bottom, y + 1.0) - max(top, float(y))
            coverage = max(0.0, min(1.0, coverage))
            if coverage:
                work[y, xs] = work[y, xs] * (1.0 - coverage) + _BLACK * coverage

    for line in verticals:
        ys = np.arange(line["draw_y0"], line["draw_y1"] + 1)
        left = line["center"] - half
        right = line["center"] + half
        for x in range(int(np.floor(left)), int(np.ceil(right))):
            if x < 0 or x >= width:
                continue
            coverage = min(right, x + 1.0) - max(left, float(x))
            coverage = max(0.0, min(1.0, coverage))
            if coverage:
                work[ys, x] = work[ys, x] * (1.0 - coverage) + _BLACK * coverage
