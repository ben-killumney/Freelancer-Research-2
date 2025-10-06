"""Simple revisit scheduling for refreshing project outcomes."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Project

OPEN_STATUSES = {"open", "pending", "unknown"}


def projects_due_for_revisit(session: Session, hours: int) -> List[Project]:
    """Return projects that should be re-crawled within the given hours."""

    threshold = datetime.utcnow() - timedelta(hours=hours)
    stmt = (
        select(Project)
        .where(Project.status.in_(OPEN_STATUSES))
        .where((Project.updated_at.is_(None)) | (Project.updated_at < threshold))
    )
    return session.execute(stmt).scalars().all()


def mark_revisited(project: Project) -> None:
    """Update the project's updated_at timestamp."""

    project.updated_at = datetime.utcnow()


__all__ = ["projects_due_for_revisit", "mark_revisited", "OPEN_STATUSES"]
