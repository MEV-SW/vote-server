from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.models import Answer, AnswerOption, Ballot, EligibleVoter, Poll, Question, QuestionOption
from app.schemas.poll import (
    AnswerSubmit,
    FormAnswerOut,
    FormOptionCount,
    FormQuestionSummary,
    FormResponseOut,
    FormResultsOut,
    FormSubmit,
)
from app.services.eligibility_service import (
    _voter_fingerprint,
    decode_voter_for_poll,
    require_active_voter,
    resolve_voter_ballot,
)
from app.services.poll_identity import is_form, is_secret
from app.services.poll_notify import notify_results_updated


def _questions(poll: Poll) -> list[Question]:
    return sorted(poll.questions, key=lambda q: (q.order_num, q.id))


def _validate_answers(poll: Poll, answers: list[AnswerSubmit]) -> dict[int, AnswerSubmit]:
    questions = {q.id: q for q in _questions(poll)}
    if not questions:
        raise HTTPException(status_code=400, detail="문항이 없는 폼입니다.")
    by_q: dict[int, AnswerSubmit] = {}
    for ans in answers:
        if ans.question_id not in questions:
            raise HTTPException(status_code=400, detail=f"알 수 없는 문항입니다: {ans.question_id}")
        if ans.question_id in by_q:
            raise HTTPException(status_code=400, detail="같은 문항에 답이 중복되었습니다.")
        by_q[ans.question_id] = ans

    for q in questions.values():
        ans = by_q.get(q.id)
        if q.required and not ans:
            raise HTTPException(status_code=400, detail=f"필수 문항입니다: {q.title}")
        if not ans:
            continue
        _validate_one(q, ans)
    return by_q


def _validate_one(q: Question, ans: AnswerSubmit) -> None:
    option_ids = {o.id for o in q.options}
    if q.type in ("short_text", "long_text"):
        text = (ans.text_value or "").strip()
        if q.required and not text:
            raise HTTPException(status_code=400, detail=f"필수 문항입니다: {q.title}")
        if q.type == "short_text" and text and "\n" in text:
            raise HTTPException(status_code=400, detail="한 줄 답변만 입력해주세요.")
        return
    if q.type == "scale":
        if ans.scale_value is None:
            if q.required:
                raise HTTPException(status_code=400, detail=f"필수 문항입니다: {q.title}")
            return
        if ans.scale_value < q.scale_min or ans.scale_value > q.scale_max:
            raise HTTPException(status_code=400, detail=f"척도는 {q.scale_min}~{q.scale_max} 사이여야 합니다.")
        return
    if q.type == "single_choice":
        if len(ans.option_ids) == 0:
            if q.required:
                raise HTTPException(status_code=400, detail=f"필수 문항입니다: {q.title}")
            return
        if len(ans.option_ids) != 1 or ans.option_ids[0] not in option_ids:
            raise HTTPException(status_code=400, detail=f"보기를 하나 선택해주세요: {q.title}")
        return
    if q.type == "multi_choice":
        if not ans.option_ids:
            if q.required:
                raise HTTPException(status_code=400, detail=f"필수 문항입니다: {q.title}")
            return
        if len(set(ans.option_ids)) != len(ans.option_ids):
            raise HTTPException(status_code=400, detail="보기가 중복되었습니다.")
        if any(oid not in option_ids for oid in ans.option_ids):
            raise HTTPException(status_code=400, detail=f"잘못된 보기입니다: {q.title}")


def _write_answers(db: Session, ballot: Ballot, by_q: dict[int, AnswerSubmit]) -> None:
    for existing in list(ballot.answers):
        db.delete(existing)
    db.flush()
    for qid, ans in by_q.items():
        row = Answer(
            ballot_id=ballot.id,
            question_id=qid,
            text_value=(ans.text_value or "").strip() or None,
            scale_value=ans.scale_value,
        )
        db.add(row)
        db.flush()
        for oid in ans.option_ids:
            db.add(AnswerOption(answer_id=row.id, option_id=oid))


def _answers_out(ballot: Ballot) -> list[AnswerSubmit]:
    out: list[AnswerSubmit] = []
    for ans in ballot.answers:
        out.append(
            AnswerSubmit(
                question_id=ans.question_id,
                text_value=ans.text_value,
                scale_value=ans.scale_value,
                option_ids=[sel.option_id for sel in ans.selected_options],
            )
        )
    return out


def _load_ballot(db: Session, ballot_id: int) -> Ballot | None:
    return (
        db.query(Ballot)
        .options(joinedload(Ballot.answers).joinedload(Answer.selected_options))
        .filter(Ballot.id == ballot_id)
        .first()
    )


def check_response(
    db: Session,
    poll: Poll,
    fingerprint: str,
    voter_token: str | None = None,
) -> tuple[bool, list[AnswerSubmit] | None]:
    if not is_form(poll):
        raise HTTPException(status_code=400, detail="폼이 아닙니다.")
    ballot = _find_identified_ballot(db, poll, fingerprint, voter_token)
    if not ballot:
        return False, None
    loaded = _load_ballot(db, ballot.id)
    return True, _answers_out(loaded) if loaded else []


def _find_identified_ballot(
    db: Session,
    poll: Poll,
    fingerprint: str,
    voter_token: str | None,
) -> Ballot | None:
    if poll.poll_type == "restricted":
        if not voter_token:
            return None
        voter_id = decode_voter_for_poll(voter_token, poll.id)
        voter = (
            db.query(EligibleVoter)
            .filter(EligibleVoter.id == voter_id, EligibleVoter.poll_id == poll.id)
            .first()
        )
        if voter:
            return resolve_voter_ballot(db, poll.id, voter)
        return (
            db.query(Ballot)
            .filter(Ballot.poll_id == poll.id, Ballot.eligible_voter_id == voter_id)
            .first()
        )
    return (
        db.query(Ballot)
        .filter(Ballot.poll_id == poll.id, Ballot.fingerprint == fingerprint)
        .first()
    )


def submit_response(db: Session, poll: Poll, body: FormSubmit) -> None:
    if poll.status != "active":
        raise HTTPException(status_code=403, detail="Poll is not active")
    if not is_form(poll):
        raise HTTPException(status_code=400, detail="폼이 아닙니다.")
    if is_secret(poll):
        raise HTTPException(status_code=400, detail="폼은 기명만 지원합니다.")

    by_q = _validate_answers(poll, body.answers)
    eligible_voter_id: int | None = None
    fingerprint = body.fingerprint

    if poll.poll_type == "restricted":
        if not body.voter_token:
            raise HTTPException(status_code=401, detail="대상자 인증이 필요합니다.")
        eligible_voter_id = decode_voter_for_poll(body.voter_token, poll.id)
        voter = require_active_voter(db, poll.id, eligible_voter_id)
        fingerprint = _voter_fingerprint(body.fingerprint, voter.id)
        existing = resolve_voter_ballot(db, poll.id, voter)
        if existing:
            loaded = _load_ballot(db, existing.id)
            if loaded:
                _write_answers(db, loaded, by_q)
                db.commit()
                notify_results_updated(poll.id)
                return
    else:
        existing = (
            db.query(Ballot)
            .filter(Ballot.poll_id == poll.id, Ballot.fingerprint == fingerprint)
            .first()
        )
        if existing:
            raise HTTPException(status_code=409, detail="Already submitted")

    ballot = Ballot(
        poll_id=poll.id,
        fingerprint=fingerprint,
        eligible_voter_id=eligible_voter_id,
    )
    db.add(ballot)
    db.flush()
    loaded = _load_ballot(db, ballot.id) or ballot
    _write_answers(db, loaded, by_q)
    db.commit()
    notify_results_updated(poll.id)


def get_form_results(db: Session, poll: Poll, *, include_responses: bool) -> FormResultsOut:
    questions = (
        db.query(Question)
        .options(joinedload(Question.options))
        .filter(Question.poll_id == poll.id)
        .order_by(Question.order_num, Question.id)
        .all()
    )
    ballots = (
        db.query(Ballot)
        .options(
            joinedload(Ballot.answers).joinedload(Answer.selected_options).joinedload(AnswerOption.option),
            joinedload(Ballot.answers).joinedload(Answer.question),
        )
        .filter(Ballot.poll_id == poll.id)
        .all()
    )
    total = len(ballots)
    eligible = poll.eligible_count or 0
    rate = (total / eligible) if eligible > 0 else 0.0

    summaries: list[FormQuestionSummary] = []
    for q in questions:
        option_counts = {o.id: 0 for o in q.options}
        scale_counts: dict[int, int] = defaultdict(int)
        texts: list[str] = []
        response_count = 0
        scale_sum = 0
        scale_n = 0
        for ballot in ballots:
            ans = next((a for a in ballot.answers if a.question_id == q.id), None)
            if not ans:
                continue
            response_count += 1
            if q.type in ("short_text", "long_text") and ans.text_value:
                if include_responses:
                    texts.append(ans.text_value)
            if q.type == "scale" and ans.scale_value is not None:
                scale_counts[ans.scale_value] += 1
                scale_sum += ans.scale_value
                scale_n += 1
            if q.type in ("single_choice", "multi_choice"):
                for sel in ans.selected_options:
                    if sel.option_id in option_counts:
                        option_counts[sel.option_id] += 1
        summaries.append(
            FormQuestionSummary(
                question_id=q.id,
                title=q.title,
                type=q.type,  # type: ignore[arg-type]
                required=q.required,
                response_count=response_count,
                option_counts=[
                    FormOptionCount(option_id=o.id, label=o.label, count=option_counts.get(o.id, 0))
                    for o in sorted(q.options, key=lambda x: x.order_num)
                ],
                scale_avg=round(scale_sum / scale_n, 2) if scale_n else None,
                scale_counts=dict(scale_counts),
                texts=texts,
            )
        )

    responses: list[FormResponseOut] = []
    if include_responses and not is_secret(poll):
        voter_ids = [b.eligible_voter_id for b in ballots if b.eligible_voter_id]
        voters = {
            v.id: v
            for v in db.query(EligibleVoter).filter(EligibleVoter.id.in_(voter_ids)).all()
        } if voter_ids else {}
        for ballot in sorted(ballots, key=lambda b: b.voted_at or b.id):
            voter = voters.get(ballot.eligible_voter_id) if ballot.eligible_voter_id else None
            answers_out: list[FormAnswerOut] = []
            for ans in ballot.answers:
                q = ans.question
                answers_out.append(
                    FormAnswerOut(
                        question_id=ans.question_id,
                        title=q.title if q else "",
                        type=(q.type if q else "short_text"),  # type: ignore[arg-type]
                        text_value=ans.text_value,
                        scale_value=ans.scale_value,
                        option_labels=[sel.option.label for sel in ans.selected_options if sel.option],
                    )
                )
            responses.append(
                FormResponseOut(
                    ballot_id=ballot.id,
                    submitted_at=ballot.voted_at,
                    voter_name=voter.name if voter else None,
                    voter_email=voter.email if voter else None,
                    answers=answers_out,
                )
            )

    return FormResultsOut(
        total_responses=total,
        eligible_count=eligible,
        participation_rate=round(rate, 4),
        questions=summaries,
        responses=responses,
    )


def form_results_csv(db: Session, poll: Poll) -> str:
    results = get_form_results(db, poll, include_responses=True)
    lines = ["ballot_id,submitted_at,voter_name,voter_email,question,type,answer"]
    for resp in results.responses:
        name = (resp.voter_name or "").replace('"', '""')
        email = (resp.voter_email or "").replace('"', '""')
        for ans in resp.answers:
            if ans.text_value:
                value = ans.text_value
            elif ans.scale_value is not None:
                value = str(ans.scale_value)
            else:
                value = "; ".join(ans.option_labels)
            value = value.replace('"', '""').replace("\n", " ")
            title = ans.title.replace('"', '""')
            lines.append(
                f'{resp.ballot_id},{resp.submitted_at.isoformat()},"{name}","{email}","{title}",{ans.type},"{value}"'
            )
    return "\n".join(lines) + "\n"
