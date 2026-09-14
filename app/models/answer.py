from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.ballot import Ballot
    from app.models.question import Question, QuestionOption


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("ballot_id", "question_id", name="uq_answer_ballot_question"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ballot_id: Mapped[int] = mapped_column(ForeignKey("ballots.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    text_value: Mapped[str | None] = mapped_column(Text)
    scale_value: Mapped[int | None] = mapped_column(Integer)

    ballot: Mapped["Ballot"] = relationship("Ballot", back_populates="answers")
    question: Mapped["Question"] = relationship("Question")
    selected_options: Mapped[list["AnswerOption"]] = relationship(
        "AnswerOption", back_populates="answer", cascade="all, delete-orphan",
    )


class AnswerOption(Base):
    __tablename__ = "answer_options"
    __table_args__ = (UniqueConstraint("answer_id", "option_id", name="uq_answer_option"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("answers.id", ondelete="CASCADE"), nullable=False)
    option_id: Mapped[int] = mapped_column(ForeignKey("question_options.id", ondelete="CASCADE"), nullable=False)

    answer: Mapped["Answer"] = relationship("Answer", back_populates="selected_options")
    option: Mapped["QuestionOption"] = relationship("QuestionOption")
