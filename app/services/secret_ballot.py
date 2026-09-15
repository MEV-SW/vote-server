import hmac
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.jwt import create_ballot_token, decode_ballot_token, hash_token
from app.config import get_settings
from app.models import Ballot, Participation, Poll

settings = get_settings()


def participation_hash(poll_id: int, subject: str) -> str:
    return hmac.new(
        settings.secret_key.encode(),
        f"{poll_id}:{subject}".encode(),
        sha256,
    ).hexdigest()


def find_participation(db: Session, poll_id: int, subject: str) -> Participation | None:
    digest = participation_hash(poll_id, subject)
    return (
        db.query(Participation)
        .filter(Participation.poll_id == poll_id, Participation.idp_sub_hash == digest)
        .first()
    )


def record_participation(db: Session, poll_id: int, subject: str) -> Participation:
    existing = find_participation(db, poll_id, subject)
    if existing:
        return existing
    row = Participation(poll_id=poll_id, idp_sub_hash=participation_hash(poll_id, subject))
    db.add(row)
    db.flush()
    return row


def issue_ballot_token(poll_id: int) -> str:
    return create_ballot_token(poll_id)


def require_ballot_token(token: str | None, poll_id: int) -> str:
    if not token:
        raise HTTPException(status_code=401, detail="익명 투표 토큰이 필요합니다.")
    decoded = decode_ballot_token(token)
    if decoded != poll_id:
        raise HTTPException(status_code=401, detail="익명 투표 토큰이 유효하지 않습니다.")
    return hash_token(token)


def ballot_by_token_hash(db: Session, poll: Poll, token_hash: str) -> Ballot | None:
    return (
        db.query(Ballot)
        .filter(Ballot.poll_id == poll.id, Ballot.ballot_token_hash == token_hash)
        .first()
    )
