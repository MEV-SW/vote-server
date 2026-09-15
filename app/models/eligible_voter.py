from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.poll import Poll


class EligibleVoter(Base):
    __tablename__ = "eligible_voters"
    __table_args__ = (
        UniqueConstraint("poll_id", "email_norm", name="uq_ev_poll_email"),
        UniqueConstraint("poll_id", "phone_norm", name="uq_ev_poll_phone"),
        UniqueConstraint("poll_id", "idp_sub", name="uq_ev_poll_idp_sub"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(30))
    name_norm: Mapped[str] = mapped_column(String(100), nullable=False)
    email_norm: Mapped[str | None] = mapped_column(String(200))
    phone_norm: Mapped[str | None] = mapped_column(String(30))
    pin_hash: Mapped[str | None] = mapped_column(String(255))
    idp_sub: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    poll: Mapped["Poll"] = relationship("Poll", back_populates="eligible_voters")
