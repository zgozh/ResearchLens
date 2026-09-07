"""modules/evaluation — 自动评测模块（Spec §B.8）。职责：观众/作者双维度 + 关键指标 + PresentQuiz + 逐断言明细。
API: compute_evaluation
评价：ResearchLens Score（双维度：忠实/易读 · 贡献/可见度）。"""
from app.services.evaluation import compute_evaluation  # noqa: F401
