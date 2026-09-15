from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Participation(Base):
    """Secret-ballot eligibility mark. No FK to ballots or choices."""

    __tablename__ = "participations"
    __table_args__ = (UniqueConstraint("poll_id", "idp_sub_hash", name="uq_participation_poll_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    idp_sub_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    poll = relationship("Poll", back_populates="participations")
