import enum
from datetime import datetime
from sqlalchemy import (
    String, Integer, DateTime, Boolean, Text, ForeignKey,
    Enum, UniqueConstraint, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

class Platform(str, enum.Enum):
    instagram = "instagram"
    facebook = "facebook"

class PostStatus(str, enum.Enum):
    new = "new"
    selected = "selected"
    generated = "generated"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    published = "published"
    failed = "failed"
    skipped = "skipped"

class JobType(str, enum.Enum):
    run_pipeline = "run_pipeline"
    publish_one = "publish_one"

class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    workspaces: Mapped[list["Workspace"]] = relationship(back_populates="owner")

class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped["User"] = relationship(back_populates="workspaces")
    config: Mapped["Config"] = relationship(back_populates="workspace", uselist=False, cascade="all, delete-orphan")
    sources: Mapped[list["SourcePage"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")

class Config(Base):
    __tablename__ = "configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_days: Mapped[int] = mapped_column(Integer, default=2)
    max_candidates: Mapped[int] = mapped_column(Integer, default=25)
    pick_top_n: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    workspace: Mapped["Workspace"] = relationship(back_populates="config")

class SourcePage(Base):
    __tablename__ = "source_pages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    platform: Mapped[Platform] = mapped_column(Enum(Platform))
    handle: Mapped[str] = mapped_column(String(255))  # username (IG) or page name/id (FB)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    workspace: Mapped["Workspace"] = relationship(back_populates="sources")

class PostCandidate(Base):
    __tablename__ = "post_candidates"
    __table_args__ = (
        UniqueConstraint("workspace_id", "platform", "original_url", name="uq_candidate_original"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    platform: Mapped[Platform] = mapped_column(Enum(Platform))
    original_url: Mapped[str] = mapped_column(String(1024))
    original_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    caption_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str] = mapped_column(String(32), default="photo")  # photo|video
    media_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    posted_at_source: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    engagement_score: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[PostStatus] = mapped_column(Enum(PostStatus), default=PostStatus.new)
    is_posted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class GeneratedContent(Base):
    __tablename__ = "generated_contents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("post_candidates.id", ondelete="CASCADE"), unique=True)
    title_en: Mapped[str] = mapped_column(String(255))
    caption_en: Mapped[str] = mapped_column(Text)
    hashtags_en: Mapped[list[str]] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class PublishJob(Base):
    __tablename__ = "publish_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    job_type: Mapped[JobType] = mapped_column(Enum(JobType))
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued)
    payload: Mapped[dict] = mapped_column(JSON)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class PublishResult(Base):
    __tablename__ = "publish_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("publish_jobs.id", ondelete="CASCADE"))
    platform: Mapped[Platform] = mapped_column(Enum(Platform))
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    remote_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remote_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class LogEvent(Base):
    __tablename__ = "log_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, index=True)
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
