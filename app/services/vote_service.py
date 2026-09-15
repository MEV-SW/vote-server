from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.models import Ballot, EligibleVoter, Poll, VoteItem
from app.schemas.poll import CheckResponse, VoteEntry, VoteSubmit
from app.services.poll_identity import is_form, is_secret
from app.services.poll_notify import notify_results_updated
from app.services.eligibility_service import (
    _voter_fingerprint,
    decode_voter_for_poll,
    require_active_voter,
    resolve_voter_ballot,
)
from app.services.secret_ballot import ballot_by_token_hash, require_ballot_token


def _validate_votes(votes: list[VoteEntry], candidate_ids: set[int], max_selections: int) -> None:
    if len(votes) < 1 or len(votes) > max_selections:
        raise HTTPException(
            status_code=400,
            detail=f"Select between 1 and {max_selections} candidate(s)",
        )

    ranks = [v.rank for v in votes]
    cids = [v.candidate_id for v in votes]
    if len(set(ranks)) != len(ranks):
        raise HTTPException(status_code=400, detail="Duplicate ranks")
    if len(set(cids)) != len(cids):
        raise HTTPException(status_code=400, detail="Duplicate candidates")

    for v in votes:
        if v.rank < 1 or v.rank > max_selections:
            raise HTTPException(status_code=400, detail=f"Rank must be between 1 and {max_selections}")
        if v.candidate_id not in candidate_ids:
            raise HTTPException(status_code=400, detail=f"Invalid candidate_id: {v.candidate_id}")


def _ballot_for_voter(db: Session, poll: Poll, voter: EligibleVoter) -> Ballot | None:
    ballot = resolve_voter_ballot(db, poll.id, voter)
    if not ballot:
        return None
    return (
        db.query(Ballot)
        .options(joinedload(Ballot.items))
        .filter(Ballot.id == ballot.id)
        .first()
    )


def _votes_from_ballot(ballot: Ballot) -> list[VoteEntry]:
    votes = [VoteEntry(rank=item.rank, candidate_id=item.candidate_id) for item in ballot.items]
    votes.sort(key=lambda v: v.rank)
    return votes


def check_vote(
    db: Session,
    poll: Poll,
    fingerprint: str,
    voter_token: str | None = None,
    ballot_token: str | None = None,
) -> CheckResponse:
    if is_form(poll):
        raise HTTPException(status_code=400, detail="폼은 /polls/{id}/check 응답 경로를 사용하세요.")

    if is_secret(poll) and poll.poll_type == "restricted":
        if not ballot_token:
            return CheckResponse(voted=False)
        token_hash = require_ballot_token(ballot_token, poll.id)
        ballot = (
            db.query(Ballot)
            .options(joinedload(Ballot.items))
            .filter(Ballot.poll_id == poll.id, Ballot.ballot_token_hash == token_hash)
            .first()
        )
        if not ballot:
            return CheckResponse(voted=False)
        return CheckResponse(voted=True, votes=_votes_from_ballot(ballot))

    if poll.poll_type == "restricted":
        if not voter_token:
            return CheckResponse(voted=False)
        voter_id = decode_voter_for_poll(voter_token, poll.id)
        voter = (
            db.query(EligibleVoter)
            .filter(EligibleVoter.id == voter_id, EligibleVoter.poll_id == poll.id)
            .first()
        )
        if voter:
            ballot = _ballot_for_voter(db, poll, voter)
        else:
            ballot = (
                db.query(Ballot)
                .options(joinedload(Ballot.items))
                .filter(Ballot.poll_id == poll.id, Ballot.eligible_voter_id == voter_id)
                .first()
            )
    else:
        ballot = (
            db.query(Ballot)
            .options(joinedload(Ballot.items))
            .filter(Ballot.poll_id == poll.id, Ballot.fingerprint == fingerprint)
            .first()
        )

    if not ballot:
        return CheckResponse(voted=False)
    return CheckResponse(voted=True, votes=_votes_from_ballot(ballot))


def _replace_items(db: Session, ballot: Ballot, votes: list[VoteEntry]) -> None:
    for item in list(ballot.items):
        db.delete(item)
    db.flush()
    for v in votes:
        db.add(VoteItem(ballot_id=ballot.id, candidate_id=v.candidate_id, rank=v.rank))


def submit_vote(db: Session, poll: Poll, body: VoteSubmit) -> None:
    if poll.status != "active":
        raise HTTPException(status_code=403, detail="Poll is not active")
    if is_form(poll):
        raise HTTPException(status_code=400, detail="폼은 /polls/{id}/responses 를 사용하세요.")

    candidate_ids = {c.id for c in poll.candidates}
    max_sel = poll.max_selections or 3
    _validate_votes(body.votes, candidate_ids, max_sel)

    if is_secret(poll) and poll.poll_type == "restricted":
        token_hash = require_ballot_token(body.ballot_token, poll.id)
        existing = ballot_by_token_hash(db, poll, token_hash)
        if existing:
            loaded = (
                db.query(Ballot)
                .options(joinedload(Ballot.items))
                .filter(Ballot.id == existing.id)
                .first()
            )
            if loaded:
                _replace_items(db, loaded, body.votes)
                db.commit()
                notify_results_updated(poll.id)
                return
        ballot = Ballot(
            poll_id=poll.id,
            fingerprint=token_hash,
            eligible_voter_id=None,
            ballot_token_hash=token_hash,
        )
        db.add(ballot)
        db.flush()
        for v in body.votes:
            db.add(VoteItem(ballot_id=ballot.id, candidate_id=v.candidate_id, rank=v.rank))
        db.commit()
        notify_results_updated(poll.id)
        return

    eligible_voter_id: int | None = None
    fingerprint = body.fingerprint

    if poll.poll_type == "restricted":
        if not body.voter_token:
            raise HTTPException(status_code=401, detail="투표 대상자 인증이 필요합니다.")
        eligible_voter_id = decode_voter_for_poll(body.voter_token, poll.id)
        voter = require_active_voter(db, poll.id, eligible_voter_id)
        fingerprint = _voter_fingerprint(body.fingerprint, voter.id)
        existing = _ballot_for_voter(db, poll, voter)
        if existing:
            _replace_items(db, existing, body.votes)
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
            raise HTTPException(status_code=409, detail="Already voted")

    ballot = Ballot(
        poll_id=poll.id,
        fingerprint=fingerprint,
        eligible_voter_id=eligible_voter_id,
    )
    db.add(ballot)
    db.flush()

    for v in body.votes:
        db.add(VoteItem(ballot_id=ballot.id, candidate_id=v.candidate_id, rank=v.rank))

    db.commit()
    notify_results_updated(poll.id)
