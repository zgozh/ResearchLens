"""SQLAlchemy ORM models — ResearchLens (Spec §18 数据模型)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    subtitle: Mapped[str] = mapped_column(String(512), default="")
    authors: Mapped[list] = mapped_column(JSON, default=list)
    year: Mapped[int] = mapped_column(Integer, default=2026)
    domain: Mapped[str] = mapped_column(String(64), default="general")
    abstract: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    pdf_url: Mapped[str] = mapped_column(String(1024), default="")
    source_mode: Mapped[str] = mapped_column(String(16), default="demo")  # demo | upload
    status: Mapped[str] = mapped_column(String(24), default="ready")
    accent: Mapped[str] = mapped_column(String(16), default="#6366F1")
    map_summary: Mapped[dict] = mapped_column(JSON, default=dict)  # paper map
    method_steps: Mapped[list] = mapped_column(JSON, default=list)  # animation steps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    pages: Mapped[list["PaperPage"]] = relationship(back_populates="paper", cascade="all, delete-orphan")
    sections: Mapped[list["Section"]] = relationship(back_populates="paper", cascade="all, delete-orphan")
    figures: Mapped[list["Figure"]] = relationship(back_populates="paper", cascade="all, delete-orphan")
    tables: Mapped[list["Table"]] = relationship(back_populates="paper", cascade="all, delete-orphan")
    claims: Mapped[list["Claim"]] = relationship(back_populates="paper", cascade="all, delete-orphan")
    scenes: Mapped[list["Scene"]] = relationship(back_populates="paper", cascade="all, delete-orphan")


class PaperPage(Base):
    __tablename__ = "paper_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    page_no: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    region_map: Mapped[dict] = mapped_column(JSON, default=dict)

    paper: Mapped["Paper"] = relationship(back_populates="pages")


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    heading: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(32), default="body")  # intro/method/.../discussion
    page: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str] = mapped_column(Text, default="")

    paper: Mapped["Paper"] = relationship(back_populates="sections")


class Figure(Base):
    __tablename__ = "figures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    fig_no: Mapped[int] = mapped_column(Integer)
    caption: Mapped[str] = mapped_column(Text, default="")
    page: Mapped[int] = mapped_column(Integer, default=1)
    image_ref: Mapped[str] = mapped_column(String(1024), default="")
    glyph_svg: Mapped[str] = mapped_column(Text, default="")
    importance: Mapped[str] = mapped_column(String(16), default="medium")

    paper: Mapped["Paper"] = relationship(back_populates="figures")


class Table(Base):
    __tablename__ = "tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    table_no: Mapped[int] = mapped_column(Integer)
    caption: Mapped[str] = mapped_column(Text, default="")
    page: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[list] = mapped_column(JSON, default=list)  # rows of cells

    paper: Mapped["Paper"] = relationship(back_populates="tables")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    claim_id: Mapped[str] = mapped_column(String(32), index=True)  # e.g. claim_07
    statement: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(32), default="RESULT")  # RESULT/METHOD/LIMITATION/CONTEXT
    confidence: Mapped[float] = mapped_column(Float, default=0.9)
    status: Mapped[str] = mapped_column(String(16), default="SUPPORTED")  # SUPPORTED | UNSUPPORTED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    paper: Mapped["Paper"] = relationship(back_populates="claims")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="claim", cascade="all, delete-orphan")


class Evidence(Base):
    __tablename__ = "evidences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"))
    page: Mapped[int] = mapped_column(Integer, default=1)
    region: Mapped[str] = mapped_column(String(64), default="")  # e.g. table_2 / fig_4 / discussion
    region_type: Mapped[str] = mapped_column(String(16), default="text")  # table|figure|text|section
    text: Mapped[str] = mapped_column(Text, default="")
    quote: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.95)

    claim: Mapped["Claim"] = relationship(back_populates="evidence")


class ResearchGraphNode(Base):
    __tablename__ = "graph_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    node_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32))  # problem/method/experiment/claim/evidence
    label: Mapped[str] = mapped_column(String(256))
    props: Mapped[dict] = mapped_column(JSON, default=dict)


class ResearchGraphEdge(Base):
    __tablename__ = "graph_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(128), default="")


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    order: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(32))  # intro/problem/method/experiment/result/limitation
    summary: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[list] = mapped_column(JSON, default=list)  # animation steps
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    narration: Mapped[dict] = mapped_column(JSON, default=dict)  # script/tts_text/subtitle/audio_url

    paper: Mapped["Paper"] = relationship(back_populates="scenes")


class Narration(Base):
    __tablename__ = "narrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    scene_id: Mapped[int] = mapped_column(Integer, default=0)
    script: Mapped[str] = mapped_column(Text, default="")
    tts_text: Mapped[str] = mapped_column(Text, default="")
    audio_url: Mapped[str] = mapped_column(String(1024), default="")
    subtitle: Mapped[str] = mapped_column(Text, default="")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    q: Mapped[str] = mapped_column(Text)
    a: Mapped[str] = mapped_column(Text)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[str] = mapped_column(String(16), default="High")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(32), default="parse")
    status: Mapped[str] = mapped_column(String(24), default="pending")  # pending/running/done/failed
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
