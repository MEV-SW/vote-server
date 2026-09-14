from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.answer import Answer
    from app.models.candidate import Candidate
    from app.models.poll import Poll


class Ballot(Base):
    __tablename__ = "ballots"
    __table_args__ = (
        UniqueConstraint("poll_id", "fingerprint", name="uq_ballot_poll_fingerprint"),
        UniqueConstraint("poll_id", "eligible_voter_id", name="uq_ballot_poll_voter"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    eligible_voter_id: Mapped[int | None] = mapped_column(
        ForeignKey("eligible_voters.id", ondelete="SET NULL"), nullable=True
    )
    voted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    poll: Mapped["Poll"] = relationship("Poll", back_populates="ballots")
    items: Mapped[list["VoteItem"]] = relationship(
        "VoteItem", back_populates="ballot", cascade="all, delete-orphan"
    )
    answers: Mapped[list["Answer"]] = relationship(
        "Answer", back_populates="ballot", cascade="all, delete-orphan"
    )


class VoteItem(Base):
    __tablename__ = "vote_items"
    __table_args__ = (
        UniqueConstraint("ballot_id", "rank", name="uq_vote_item_ballot_rank"),
        UniqueConstraint("ballot_id", "candidate_id", name="uq_vote_item_ballot_candidate"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ballot_id: Mapped[int] = mapped_column(ForeignKey("ballots.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    ballot: Mapped["Ballot"] = relationship("Ballot", back_populates="items")
    candidate: Mapped["Candidate"] = relationship("Candidate")
