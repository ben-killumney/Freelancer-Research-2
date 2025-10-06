"""Database utilities and persistence helpers."""

from __future__ import annotations

import contextlib
import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

import pandas as pd
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base, Bid, Project, ProjectStatusSnapshot, User

LOGGER = logging.getLogger(__name__)


_ENGINE: Optional[Engine] = None
_SESSION_FACTORY: Optional[sessionmaker] = None


def get_engine() -> Engine:
    """Return a lazily initialised SQLAlchemy engine."""

    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(settings.database_url, future=True)
    return _ENGINE


def get_session_factory() -> sessionmaker:
    """Return a configured session factory."""

    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SESSION_FACTORY


@contextlib.contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""

    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:  # pragma: no cover - safeguard
        session.rollback()
        raise
    finally:
        session.close()


def init_db(drop_existing: bool = False) -> None:
    """Create database tables, optionally dropping existing ones."""

    engine = get_engine()
    if drop_existing:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def hash_handle(handle: str, salt: str) -> str:
    """Return a SHA256 hash of the freelancer handle using the provided salt."""

    digest = hashlib.sha256()
    digest.update(salt.encode("utf-8"))
    digest.update(handle.encode("utf-8"))
    return digest.hexdigest()


def upsert_user(session: Session, user_data: Dict[str, Any]) -> User:
    """Insert or update a :class:`User` record and return it."""

    user_id = user_data["user_id"]
    instance = session.get(User, user_id)
    if instance:
        for key, value in user_data.items():
            setattr(instance, key, value)
    else:
        instance = User(**user_data)
        session.add(instance)
    return instance


def upsert_project(session: Session, project_data: Dict[str, Any]) -> Project:
    """Insert or update a :class:`Project` record and return it."""

    project_id = project_data["project_id"]
    instance = session.get(Project, project_id)
    if instance:
        for key, value in project_data.items():
            setattr(instance, key, value)
    else:
        instance = Project(**project_data)
        session.add(instance)
    return instance


def upsert_bid(session: Session, bid_data: Dict[str, Any]) -> Bid:
    """Insert or update a :class:`Bid` record and return it."""

    bid_id = bid_data["bid_id"]
    instance = session.get(Bid, bid_id)
    if instance:
        for key, value in bid_data.items():
            setattr(instance, key, value)
    else:
        instance = Bid(**bid_data)
        session.add(instance)
    return instance


def update_project_bid_metrics(session: Session, project_id: int) -> None:
    """Recompute bid aggregates for a project."""

    bids_subquery = (
        select(
            func.count(Bid.bid_id),
            func.avg(Bid.amount),
            func.min(Bid.amount),
            func.max(Bid.amount),
        )
        .where(Bid.project_id == project_id)
        .subquery()
    )
    count, avg, min_bid, max_bid = session.execute(select(bids_subquery)).one()

    project = session.get(Project, project_id)
    if project is None:
        LOGGER.warning("Project %s not found when updating metrics", project_id)
        return

    project.num_bids_reported = count or 0
    project.avg_bid_reported = float(avg) if avg is not None else None
    project.updated_at = datetime.utcnow()

    if count:
        snapshot = ProjectStatusSnapshot(
            project_id=project_id,
            snapshot_at=datetime.utcnow(),
            status=project.status,
            num_bids=count or 0,
            min_bid=float(min_bid) if min_bid is not None else None,
            max_bid=float(max_bid) if max_bid is not None else None,
            avg_bid=float(avg) if avg is not None else None,
        )
        session.add(snapshot)


def compute_bid_positions(session: Session, project_id: int) -> None:
    """Assign rank positions to bids ordered by amount."""

    bids = (
        session.execute(
            select(Bid).where(Bid.project_id == project_id).order_by(Bid.amount.asc(), Bid.placed_at.asc())
        )
        .scalars()
        .all()
    )
    for idx, bid in enumerate(bids, start=1):
        bid.bid_position_from_lowest = idx


def determine_winner(session: Session, project: Project) -> None:
    """Flag the winning bid if the project has an awarded freelancer."""

    if project.awarded_to_id is None:
        return
    winning_bid = (
        session.execute(
            select(Bid)
            .where(Bid.project_id == project.project_id, Bid.bidder_id == project.awarded_to_id)
            .order_by(Bid.placed_at.desc())
        )
        .scalars()
        .first()
    )
    if winning_bid:
        winning_bid.is_winner = True


def fetch_winners_curse_features(session: Session) -> pd.DataFrame:
    """Return per-project aggregates useful for winner's curse analysis."""

    projects_stmt = select(
        Project.project_id,
        Project.num_bids_reported,
        Project.avg_bid_reported,
    )
    bids_stmt = select(Bid.project_id, Bid.amount, Bid.is_winner)

    project_rows = session.execute(projects_stmt).all()
    bid_rows = session.execute(bids_stmt).all()

    bids_by_project: Dict[int, List[float]] = {}
    winners_by_project: Dict[int, Optional[float]] = {}
    for project_id, amount, is_winner in bid_rows:
        if amount is not None:
            bids_by_project.setdefault(project_id, []).append(float(amount))
        if is_winner and amount is not None:
            winners_by_project[project_id] = float(amount)

    records = []
    for project_id, num_bids, avg_bid in project_rows:
        bids = sorted(bids_by_project.get(project_id, []))
        min_bid = bids[0] if bids else None
        max_bid = bids[-1] if bids else None
        median_bid = None
        std_bid = None
        if bids:
            midpoint = len(bids) // 2
            if len(bids) % 2 == 0:
                median_bid = (bids[midpoint - 1] + bids[midpoint]) / 2
            else:
                median_bid = bids[midpoint]
            std_bid = float(pd.Series(bids).std(ddof=0)) if len(bids) > 1 else 0.0
        winning_bid = winners_by_project.get(project_id)
        record = {
            "project_id": project_id,
            "n_bids": num_bids,
            "mean_bid": float(avg_bid) if avg_bid is not None else None,
            "median_bid": median_bid,
            "min_bid": min_bid,
            "max_bid": max_bid,
            "std_bid": std_bid,
            "winning_bid": winning_bid,
            "winning_minus_median": (winning_bid - median_bid) if (winning_bid is not None and median_bid is not None) else None,
            "winning_percent_above_min": ((winning_bid - min_bid) / min_bid) if (winning_bid is not None and min_bid) else None,
        }
        records.append(record)
    return pd.DataFrame.from_records(records)


__all__ = [
    "get_engine",
    "get_session_factory",
    "session_scope",
    "init_db",
    "hash_handle",
    "upsert_user",
    "upsert_project",
    "upsert_bid",
    "update_project_bid_metrics",
    "compute_bid_positions",
    "determine_winner",
    "fetch_winners_curse_features",
]
