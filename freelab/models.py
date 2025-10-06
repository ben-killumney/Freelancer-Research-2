"""SQLAlchemy models for the freelab project."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class TimestampMixin:
    """Timestamp helpers for created/updated columns."""

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class User(Base, TimestampMixin):
    """Freelancer.com user profile."""

    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True)
    handle_hash = Column(String(64), nullable=False, index=True)
    country = Column(String(128))
    rating = Column(Float)
    reviews_count = Column(Integer)
    member_since = Column(Date)
    verified_json = Column(JSON)
    role = Column(String(32))

    bids = relationship("Bid", back_populates="bidder")
    projects_posted = relationship("Project", foreign_keys="Project.employer_id", back_populates="employer")

    __table_args__ = (
        Index("ix_users_country", "country"),
    )


class Project(Base, TimestampMixin):
    """Freelancer.com project details."""

    __tablename__ = "projects"

    project_id = Column(Integer, primary_key=True)
    url = Column(String(512), nullable=False, unique=True)
    title = Column(String(512), nullable=False)
    category = Column(String(128))
    subcategory = Column(String(128))
    description_text = Column(Text)
    budget_type = Column(String(32))
    min_budget = Column(Numeric(12, 2))
    max_budget = Column(Numeric(12, 2))
    currency = Column(String(16))
    posted_at = Column(DateTime)
    employer_id = Column(Integer, ForeignKey("users.user_id"), index=True)
    employer_country = Column(String(128))
    num_bids_reported = Column(Integer)
    avg_bid_reported = Column(Float)
    status = Column(String(32), index=True)
    awarded_to_id = Column(Integer, ForeignKey("users.user_id"), nullable=True, index=True)
    awarded_at = Column(DateTime)
    accepted_at = Column(DateTime)
    closed_at = Column(DateTime)

    employer = relationship("User", foreign_keys=[employer_id], back_populates="projects_posted")
    awarded_to = relationship("User", foreign_keys=[awarded_to_id])
    bids = relationship("Bid", back_populates="project")

    __table_args__ = (
        Index("ix_projects_status_posted", "status", "posted_at"),
        Index("ix_projects_category_status", "category", "status"),
    )


class Bid(Base, TimestampMixin):
    """Bid placed on a project."""

    __tablename__ = "bids"

    bid_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.project_id"), nullable=False, index=True)
    bidder_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2))
    currency = Column(String(16))
    delivery_days = Column(Integer)
    placed_at = Column(DateTime)
    is_winner = Column(Boolean, default=False, nullable=False, index=True)
    bid_position_from_lowest = Column(Integer)
    text_excerpt = Column(Text)

    project = relationship("Project", back_populates="bids")
    bidder = relationship("User", back_populates="bids")

    __table_args__ = (
        Index("ix_bids_project_amount", "project_id", "amount"),
        Index("ix_bids_bidder", "bidder_id"),
    )


class ProjectStatusSnapshot(Base):
    """Historical status for a project."""

    __tablename__ = "project_status_snapshots"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.project_id"), nullable=False, index=True)
    snapshot_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    status = Column(String(32), nullable=False)
    num_bids = Column(Integer)
    min_bid = Column(Numeric(12, 2))
    max_bid = Column(Numeric(12, 2))
    avg_bid = Column(Numeric(12, 2))

    project = relationship("Project")

    __table_args__ = (
        Index("ix_project_snapshot_time", "project_id", "snapshot_at"),
    )


class UserProfileSnapshot(Base):
    """Historical user metrics for access-cliff research."""

    __tablename__ = "user_profile_snapshots"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    snapshot_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    rating = Column(Float)
    reviews_count = Column(Integer)
    wins_count = Column(Integer)

    user = relationship("User")

    __table_args__ = (
        Index("ix_user_snapshot_time", "user_id", "snapshot_at"),
    )


__all__ = [
    "Base",
    "User",
    "Project",
    "Bid",
    "ProjectStatusSnapshot",
    "UserProfileSnapshot",
]
