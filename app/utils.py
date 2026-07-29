MM_PER_INCH = 25.4
PT_PER_INCH = 72
MM_TO_PT = PT_PER_INCH / MM_PER_INCH


def mm_to_pt(mm):
    return mm * MM_TO_PT


def pt_to_mm(pt):
    return pt / MM_TO_PT


def pt_to_px(pt, dpi=96):
    return pt * dpi / PT_PER_INCH


def px_to_pt(px, dpi=96):
    return px * PT_PER_INCH / dpi


def snap_value(value, snap_points, threshold=5):
    best = value
    best_dist = threshold + 1
    for sp in snap_points:
        dist = abs(value - sp)
        if dist < best_dist:
            best_dist = dist
            best = sp
    return best


def parse_page_range(text, max_pages):
    if max_pages <= 0:
        return []
    selected = set()
    parts = text.replace(" ", "").split(",")
    for part in parts:
        if not part:
            continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                start = int(a)
                end = int(b)
            except ValueError:
                continue
            for p in range(max(1, start), min(max_pages, end) + 1):
                selected.add(p - 1)
        else:
            try:
                p = int(part)
                if 1 <= p <= max_pages:
                    selected.add(p - 1)
            except ValueError:
                continue
    return sorted(selected)
