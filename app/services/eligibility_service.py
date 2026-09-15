import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.jwt import create_voter_token, decode_voter_token, hash_password, verify_password
from app.models import Ballot, EligibleVoter, Poll
from app.services.poll_identity import is_secret
from app.services.secret_ballot import find_participation, issue_ballot_token, record_participation
from app.services.verify_fields import parse_verify_fields

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PIN_RE = re.compile(r"^\d{4}$")
_FIELD_LABEL = {"name": "이름", "email": "이메일", "phone": "전화번호"}


def normalize_name(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    return re.sub(r"\s+", " ", value.strip().lower())


def normalize_email(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    email = value.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="올바른 이메일 형식이 아닙니다.")
    return email


def normalize_phone(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) < 9:
        raise HTTPException(status_code=400, detail="올바른 전화번호 형식이 아닙니다.")
    return digits


def sync_eligible_count(db: Session, poll_id: int) -> None:
    poll = db.query(Poll).filter(Poll.id == poll_id).first()
    if not poll or poll.poll_type != "restricted":
        return
    count = db.query(EligibleVoter).filter(EligibleVoter.poll_id == poll_id).count()
    poll.eligible_count = count
    db.commit()


def _voter_fingerprint(fp: str, voter_id: int) -> str:
    return f"{fp}:{voter_id}"[:64]


def _normalize_input(field: str, raw: str | None) -> str | None:
    if field == "name":
        return normalize_name(raw)
    if field == "email":
        return normalize_email(raw)
    if field == "phone":
        return normalize_phone(raw)
    return None


def _collect_input_values(
    fields: list[str],
    *,
    name: str | None,
    email: str | None,
    phone: str | None,
) -> dict[str, str]:
    raw = {"name": name, "email": email, "phone": phone}
    values: dict[str, str] = {}
    for field in fields:
        norm = _normalize_input(field, raw.get(field))
        if not norm:
            label = _FIELD_LABEL.get(field, field)
            raise HTTPException(status_code=400, detail=f"{label}을(를) 입력해주세요.")
        values[field] = norm
    return values


def _voter_field_value(voter: EligibleVoter, field: str) -> str | None:
    if field == "name":
        return voter.name_norm
    if field == "email":
        return voter.email_norm
    if field == "phone":
        return voter.phone_norm
    return None


def _voter_matches(voter: EligibleVoter, fields: list[str], values: dict[str, str]) -> bool:
    return all(_voter_field_value(voter, field) == values.get(field) for field in fields)


def resolve_voter_ballot(
    db: Session,
    poll_id: int,
    voter: EligibleVoter,
    voters: list[EligibleVoter] | None = None,
) -> Ballot | None:
    """Find a ballot for a registered voter, including orphaned records after re-registration."""
    if voters is None:
        voters = db.query(EligibleVoter).filter(EligibleVoter.poll_id == poll_id).all()

    voter_ids = {v.id for v in voters}
    all_ballots = db.query(Ballot).filter(Ballot.poll_id == poll_id).all()
    linked: dict[int, Ballot] = {}
    orphans: list[Ballot] = []
    for ballot in all_ballots:
        vid = ballot.eligible_voter_id
        if vid and vid in voter_ids:
            linked[vid] = ballot
        else:
            orphans.append(ballot)

    if voter.id in linked:
        return linked[voter.id]

    suffix = f":{voter.id}"
    for ballot in all_ballots:
        if ballot.fingerprint.endswith(suffix):
            return ballot

    if len(voters) == 1 and len(orphans) == 1 and voters[0].id == voter.id:
        return orphans[0]

    return None


def require_active_voter(db: Session, poll_id: int, voter_id: int) -> EligibleVoter:
    voter = (
        db.query(EligibleVoter)
        .filter(EligibleVoter.id == voter_id, EligibleVoter.poll_id == poll_id)
        .first()
    )
    if not voter:
        raise HTTPException(
            status_code=401,
            detail="대상자 정보가 변경되었습니다. 다시 본인 확인해주세요.",
        )
    return voter


def _display_name(voter: EligibleVoter, fields: list[str]) -> str:
    if "name" in fields and voter.name:
        return voter.name
    if voter.email:
        return voter.email
    if voter.phone:
        return voter.phone
    return voter.name or "대상자"


def _validate_pin(pin: str | None) -> str:
    if not pin or not _PIN_RE.match(pin):
        raise HTTPException(status_code=400, detail="4자리 숫자 비밀번호를 입력해주세요.")
    return pin


def verify_voter(
    db: Session,
    poll: Poll,
    *,
    name: str | None,
    email: str | None,
    phone: str | None,
    pin: str | None = None,
) -> dict:
    if poll.poll_type != "restricted":
        raise HTTPException(status_code=400, detail="This poll does not require verification")

    fields = parse_verify_fields(poll.verify_fields)
    values = _collect_input_values(fields, name=name, email=email, phone=phone)

    voters = db.query(EligibleVoter).filter(EligibleVoter.poll_id == poll.id).all()
    matched = [v for v in voters if _voter_matches(v, fields, values)]

    if not matched:
        raise HTTPException(status_code=403, detail="등록된 투표 대상자가 아닙니다.")
    if len(matched) > 1:
        raise HTTPException(status_code=403, detail="입력한 정보가 여러 대상자와 일치합니다. 운영팀에 문의해주세요.")

    voter = matched[0]
    display = _display_name(voter, fields)
    if is_secret(poll):
        already_voted = find_participation(db, poll.id, f"pin:{voter.id}") is not None
    else:
        already_voted = resolve_voter_ballot(db, poll.id, voter, voters) is not None
    pin_setup = voter.pin_hash is None
    identity_mode = "secret" if is_secret(poll) else "identified"

    if not pin:
        return {
            "verified": False,
            "voter_token": None,
            "ballot_token": None,
            "voter_name": display,
            "already_voted": already_voted,
            "pin_required": True,
            "pin_setup": pin_setup,
            "identity_mode": identity_mode,
        }

    pin_value = _validate_pin(pin)
    if pin_setup:
        voter.pin_hash = hash_password(pin_value)
        db.commit()
    elif not verify_password(pin_value, voter.pin_hash or ""):
        raise HTTPException(status_code=403, detail="비밀번호가 일치하지 않습니다.")

    if is_secret(poll):
        return _secret_pin_result(db, poll, voter)

    token = create_voter_token(poll.id, voter.id)
    return {
        "verified": True,
        "voter_token": token,
        "ballot_token": None,
        "voter_name": display,
        "already_voted": already_voted,
        "pin_required": False,
        "pin_setup": False,
        "identity_mode": "identified",
    }


def _secret_pin_result(db: Session, poll: Poll, voter: EligibleVoter) -> dict:
    subject = f"pin:{voter.id}"
    already = find_participation(db, poll.id, subject) is not None
    if already:
        return {
            "verified": True,
            "voter_token": None,
            "ballot_token": None,
            "voter_name": "투표자",
            "already_voted": True,
            "pin_required": False,
            "pin_setup": False,
            "identity_mode": "secret",
        }
    record_participation(db, poll.id, subject)
    db.commit()
    return {
        "verified": True,
        "voter_token": None,
        "ballot_token": issue_ballot_token(poll.id),
        "voter_name": "투표자",
        "already_voted": False,
        "pin_required": False,
        "pin_setup": False,
        "identity_mode": "secret",
    }


def decode_voter_for_poll(token: str, poll_id: int) -> int:
    decoded = decode_voter_token(token)
    if not decoded:
        raise HTTPException(status_code=401, detail="인증이 만료되었거나 유효하지 않습니다.")
    token_poll_id, voter_id = decoded
    if token_poll_id != poll_id:
        raise HTTPException(status_code=401, detail="인증이 만료되었거나 유효하지 않습니다.")
    return voter_id
