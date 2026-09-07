"""modules/scene — 场景化讲解模块（Spec §B.6，Presenter）。职责：自顶向下分层规划（高层场景→低层步骤+讲解词+证据+图）。
API: get_presentation
评价：讲解词与论文一致性（Alignment）、讲解覆盖（Professionalism）。"""
from app.services.presentation import get_presentation  # noqa: F401
