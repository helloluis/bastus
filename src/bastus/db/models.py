"""ORM models. The runs table's integer PK IS the numeric run id, assigned at
creation (before provisioning) so that even failed/invalid runs are identified.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    state: Mapped[str] = mapped_column(String(32), default="requested", index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # RunConfig.parameters_summary()
    total_goals: Mapped[int] = mapped_column(Integer, default=0)
    total_breaks: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    goals: Mapped[list[GoalRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    turns: Mapped[list[TurnRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class GoalRow(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    goal_key: Mapped[str] = mapped_column(String(32))  # "g1"
    category: Mapped[str] = mapped_column(String(8))
    objective: Mapped[str] = mapped_column(Text)
    seed_image_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    broken: Mapped[bool] = mapped_column(default=False)
    best_harm: Mapped[float] = mapped_column(Float, default=0.0)

    run: Mapped[RunRow] = relationship(back_populates="goals")


class TurnRow(Base):
    __tablename__ = "turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    goal_key: Mapped[str] = mapped_column(String(32), index=True)
    branch_id: Mapped[int] = mapped_column(Integer)
    depth: Mapped[int] = mapped_column(Integer)
    attacker_text: Mapped[str] = mapped_column(Text)
    target_text: Mapped[str] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(String(16))
    harm: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(8), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    run: Mapped[RunRow] = relationship(back_populates="turns")
