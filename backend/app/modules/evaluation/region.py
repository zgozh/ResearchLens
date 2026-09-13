"""区域几何：单位对齐 + IoU（R4-M6，ADR D-107）。

**为什么单独一个模块**：`anchor_region_hit_rate` 的两件危险事都发生在这里 ——

1. **单位混用**：MinerU 的 bbox 是 0–1000 归一化网格，PyMuPDF 的是 PDF point。
   不换算直接相减会得到一个"看起来正常"的错值（比报错更危险）。
2. **自证 IoU**：如果"期望区域"与"实际区域"来自**同一个块的同一个矩形**，
   IoU 恒为 1.0 —— 一个漂亮的满分，但它什么都没验证。

所以本模块把这两个风险变成**显式参数**：算之前必须声明单位、必须声明来源是否独立。
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

Rect = Sequence[float]

#: 本项目的 Rect 契约空间：**0..1 归一化**（`contracts/common.validate_rect`）。
#: 注意区分：MinerU 的 `bbox_units="normalized"` 指的是 **0–1000 网格**，
#: 不是这个空间 —— 实测就是因为把两者当成同一个而当场被契约拦下。
RECT_SPACE_MAX = 1.0
#: MinerU 归一化网格的上界
MINERU_GRID_MAX = 1000.0


def normalize_rect(
    rect: Optional[Rect],
    units: str,
    *,
    page_size: Optional[Tuple[float, float]] = None,
) -> Optional[list]:
    """把矩形统一到本项目的 **0..1** 空间；做不到就返回 ``None``（不猜）。

    - ``normalized``：MinerU 的 0–1000 网格 → 除以 1000；
    - ``unit_0_1``：已经是契约空间，原样；
    - ``point``：需要页宽/高（PDF point）。**缺页尺寸就返回 None** ——
      没有页尺寸的换算只是拍脑袋；
    - 其它（``pixel`` / ``unknown`` / 空）：返回 ``None``。
      ``pixel`` 需要 DPI 才能转 point，当前链路拿不到，所以**诚实地说算不了**。
    """
    if not rect or len(rect) < 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in rect[:4])
    except (TypeError, ValueError):
        return None
    unit = (units or "").strip().lower()
    if unit == "normalized":
        return [x0 / MINERU_GRID_MAX, y0 / MINERU_GRID_MAX,
                x1 / MINERU_GRID_MAX, y1 / MINERU_GRID_MAX]
    if unit == "unit_0_1":
        return [x0, y0, x1, y1]
    if unit == "point":
        if not page_size:
            return None
        width, height = (float(page_size[0]), float(page_size[1]))
        if width <= 0 or height <= 0:
            return None
        return [x0 / width, y0 / height, x1 / width, y1 / height]
    return None


def _area(rect: Rect) -> float:
    w = max(0.0, float(rect[2]) - float(rect[0]))
    h = max(0.0, float(rect[3]) - float(rect[1]))
    return w * h


def rect_iou(a: Rect, b: Rect) -> float:
    """两个**已对齐单位**矩形的交并比。"""
    ix0 = max(float(a[0]), float(b[0]))
    iy0 = max(float(a[1]), float(b[1]))
    ix1 = min(float(a[2]), float(b[2]))
    iy1 = min(float(a[3]), float(b[3]))
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = _area(a) + _area(b) - inter
    if union <= 0:
        return 0.0
    return inter / union


def region_iou_or_none(
    *,
    expected: Optional[Rect],
    actual: Optional[Rect],
    independent: bool,
) -> Optional[float]:
    """算区域 IoU；**来源不独立时拒绝计算**（返回 ``None``）。

    `independent=False` 的含义是"期望区域与实际区域同源"（例如两个值都由
    同一个引用块的 bbox 派生）。此时 IoU 恒为 1.0，算出来只会是一个
    **自证的满分**，比"未评测"更糟 —— 所以这里显式拒绝。

    缺任一矩形同样返回 ``None``（宁缺勿造）。
    """
    if expected is None or actual is None:
        return None
    if not independent:
        return None
    if len(expected) < 4 or len(actual) < 4:
        return None
    return rect_iou(expected, actual)


def normalize_rect_from_block(raw_ref) -> Optional[list]:
    """从块的 `raw_ref`（**dict 形态**，来自 `blocks.raw_ref` JSON 列）取 0..1 矩形。

    与 `evidence.gate.block_rect`（对象形态）是同一套换算规则的 dict 版本 ——
    评测层从库里读出来的是 JSON dict，不是 pydantic 对象；两处必须换算一致，
    否则区域指标会一边一个单位。
    """
    if not isinstance(raw_ref, dict):
        return None
    return normalize_rect(raw_ref.get("bbox_values"), raw_ref.get("bbox_units") or "")


__all__ = [
    "RECT_SPACE_MAX",
    "MINERU_GRID_MAX",
    "normalize_rect",
    "normalize_rect_from_block",
    "rect_iou",
    "region_iou_or_none",
]
