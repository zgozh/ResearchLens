"""modules/visual — 程序化渲染模块（Spec §B.9）。职责：把 table/figure/method_steps/graph 渲染成 SVG/Canvas 原图。
API: pipeline / bar_chart / line_chart / matrix / scatter / architecture（见 seed.svgkit）
评价：视觉一致性、Aesthetic。"""
from app.seed import svgkit  # noqa: F401  (render utilities)
