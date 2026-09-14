from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Ballot, Candidate, Poll, Question
from app.schemas.poll import (
    CheckResponse,
    FormResultsOut,
    FormSubmit,
    PollOut,
    PollPublicListItem,
    PollPublicOut,
    ResultsOut,
    VerifyVoterRequest,
    VerifyVoterResponse,
    VoteSubmit,
)
from app.services.aggregate_service import get_results
from app.services.eligibility_service import verify_voter
from app.services.form_service import check_response, get_form_results, submit_response
from app.services.poll_identity import is_form
from app.services.vote_service import check_vote, submit_vote

router = APIRouter(prefix="/polls", tags=["polls"])


def _question_options(query):
    return query.options(
        joinedload(Poll.candidates),
        joinedload(Poll.questions).joinedload(Question.options),
    )


@router.get("", response_model=list[PollPublicListItem])
def list_polls_public(db: Session = Depends(get_db)) -> list[PollPublicListItem]:
    polls = (
        db.query(Poll)
        .filter(Poll.status.in_(("active", "closed")))
        .order_by(case((Poll.status == "active", 0), else_=1), Poll.created_at.desc())
        .all()
    )
    items: list[PollPublicListItem] = []
    for p in polls:
        cand_count = db.query(func.count(Candidate.id)).filter(Candidate.poll_id == p.id).scalar() or 0
        question_count = db.query(func.count(Question.id)).filter(Question.poll_id == p.id).scalar() or 0
        ballot_count = db.query(func.count(Ballot.id)).filter(Ballot.poll_id == p.id).scalar() or 0
        items.append(
            PollPublicListItem(
                id=p.id,
                title=p.title,
                category=p.category,
                status=p.status,
                candidates=cand_count,
                questions=question_count,
                max_selections=p.max_selections or 3,
                poll_type=p.poll_type or "open",
                kind=p.kind or "vote",
                identity_mode=p.identity_mode or "secret",
                ballots=ballot_count,
                closes_at=p.closes_at,
                desc=p.description,
            )
        )
    return items


def _get_poll_or_404(db: Session, poll_id: int) -> Poll:
    poll = _question_options(db.query(Poll)).filter(Poll.id == poll_id).first()
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    return poll


@router.get("/{poll_id}/public", response_model=PollPublicOut)
def get_poll_public(poll_id: int, db: Session = Depends(get_db)) -> Poll:
    return _get_poll_or_404(db, poll_id)


@router.get("/{poll_id}/results", response_model=ResultsOut)
def get_poll_results_public(poll_id: int, db: Session = Depends(get_db)) -> ResultsOut:
    poll = _get_poll_or_404(db, poll_id)
    if poll.status != "closed":
        raise HTTPException(status_code=403, detail="투표가 종료된 후에만 결과를 확인할 수 있습니다.")
    if is_form(poll):
        raise HTTPException(status_code=400, detail="폼 결과는 /polls/{id}/form-results 를 사용하세요.")
    return get_results(db, poll_id, poll.eligible_count)


@router.get("/{poll_id}/form-results", response_model=FormResultsOut)
def get_form_results_public(poll_id: int, db: Session = Depends(get_db)) -> FormResultsOut:
    poll = _get_poll_or_404(db, poll_id)
    if not is_form(poll):
        raise HTTPException(status_code=400, detail="폼이 아닙니다.")
    if poll.status != "closed":
        raise HTTPException(status_code=403, detail="종료된 후에만 결과를 확인할 수 있습니다.")
    return get_form_results(db, poll, include_responses=False)


@router.get("/{poll_id}", response_model=PollOut)
def get_poll(poll_id: int, db: Session = Depends(get_db)) -> Poll:
    poll = _get_poll_or_404(db, poll_id)
    if poll.status not in ("active", "closed"):
        raise HTTPException(status_code=403, detail="Poll is not available")
    return poll


@router.post("/{poll_id}/verify", response_model=VerifyVoterResponse)
def verify_poll_voter(
    poll_id: int,
    body: VerifyVoterRequest,
    db: Session = Depends(get_db),
) -> VerifyVoterResponse:
    poll = _get_poll_or_404(db, poll_id)
    if poll.status not in ("active", "closed"):
        raise HTTPException(status_code=403, detail="Poll is not available")
    result = verify_voter(
        db,
        poll,
        name=body.name,
        email=body.email,
        phone=body.phone,
        pin=body.pin,
    )
    return VerifyVoterResponse(**result)


@router.get("/{poll_id}/check", response_model=CheckResponse)
def check_poll_vote(
    poll_id: int,
    fingerprint: str = Query(..., min_length=8, max_length=64),
    voter_token: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CheckResponse:
    poll = _get_poll_or_404(db, poll_id)
    if is_form(poll):
        voted, answers = check_response(db, poll, fingerprint, voter_token)
        return CheckResponse(voted=voted, answers=answers)
    return check_vote(db, poll, fingerprint, voter_token)


@router.post("/{poll_id}/vote", status_code=201)
def vote_poll(poll_id: int, body: VoteSubmit, db: Session = Depends(get_db)) -> dict:
    poll = _get_poll_or_404(db, poll_id)
    submit_vote(db, poll, body)
    return {"ok": True}


@router.post("/{poll_id}/responses", status_code=201)
def submit_form(poll_id: int, body: FormSubmit, db: Session = Depends(get_db)) -> dict:
    poll = _get_poll_or_404(db, poll_id)
    submit_response(db, poll, body)
    return {"ok": True}
