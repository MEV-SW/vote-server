from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.ballot import Ballot
    from app.models.candidate import Candidate
    from app.models.eligible_voter import EligibleVoter
    from app.models.participation import Participation
    from app.models.question import Question


class Poll(Base):
    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), default="기타")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | active | closed
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    eligible_count: Mapped[int] = mapped_column(Integer, default=0)
    max_selections: Mapped[int] = mapped_column(Integer, default=3)
    poll_type: Mapped[str] = mapped_column(String(20), default="open")  # open | restricted
    verify_fields: Mapped[str] = mapped_column(String(50), default="name,email,phone")
    kind: Mapped[str] = mapped_column(String(20), default="vote")  # vote | form
    verify_method: Mapped[str] = mapped_column(String(20), default="pin")  # pin | sso
    identity_mode: Mapped[str] = mapped_column(String(20), default="secret")  # identified | secret
    owner_id: Mapped[str | None] = mapped_column(String(200))
    owner_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    candidates: Mapped[list["Candidate"]] = relationship(
        "Candidate", back_populates="poll", cascade="all, delete-orphan"
    )
    questions: Mapped[list["Question"]] = relationship(
        "Question", back_populates="poll", cascade="all, delete-orphan",
        order_by="Question.order_num",
    )
    ballots: Mapped[list["Ballot"]] = relationship(
        "Ballot", back_populates="poll", cascade="all, delete-orphan"
    )
    eligible_voters: Mapped[list["EligibleVoter"]] = relationship(
        "EligibleVoter", back_populates="poll", cascade="all, delete-orphan"
    )
    participations: Mapped[list["Participation"]] = relationship(
        "Participation", back_populates="poll", cascade="all, delete-orphan"
    )
