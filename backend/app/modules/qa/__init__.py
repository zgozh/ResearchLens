"""modules/qa — 证据问答模块（Spec §B.7）。职责：Retrieval→Evidence→Answer；多轮；PresentQuiz 出题判分。
API: answer_question
评价：Answer Grounding、Quiz 命中率。"""
from app.services.qa import answer_question  # noqa: F401
