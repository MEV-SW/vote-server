import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.auth.deps import get_current_admin
from app.auth.jwt import create_access_token, hash_password, verify_password
from app.config import get_settings
from app.database import get_db
from app.models import Admin, Ballot, Candidate, EligibleVoter, Poll, Question, QuestionOption
from app.schemas.admin import (
    LoginRequest,
    PresignRequest,
    PresignResponse,
    ResetVotesResponse,
    TokenResponse,
    UploadResponse,
)
from app.services.eligibility_service import resolve_voter_ballot
from app.services.poll_notify import notify_poll_updated, notify_results_updated, notify_voters_updated
from app.services.s3_service import create_presigned_upload, delete_media_file
from app.schemas.poll import (
    CandidateCreate,
    CandidateOut,
    CandidateUpdate,
    EligibleVoterBulkCreate,
    EligibleVoterCreate,
    EligibleVoterOut,
    FormResultsOut,
    QuestionCreate,
    QuestionOptionCreate,
    QuestionOptionOut,
    QuestionOptionUpdate,
    QuestionOut,
    QuestionUpdate,
    RevokeVoterVoteResponse,
    PollCreate,
    PollListItem,
    PollOut,
    PollUpdate,
    ResultsOut,
)
from app.services.eligibility_service import (
    _collect_input_values,
    normalize_email,
    normalize_name,
    normalize_phone,
    sync_eligible_count,
)
from app.services.verify_fields import parse_verify_fields, serialize_verify_fields
from app.services.aggregate_service import get_results, results_csv
from app.services.form_service import form_results_csv, get_form_results
from app.services.poll_identity import is_form

router = APIRouter(prefix="/admin", tags=["admin"])
settings = get_settings()


def _poll_with_relations(db: Session, poll_id: int) -> Poll | None:
    return (
        db.query(Poll)
        .options(
            joinedload(Poll.candidates),
            joinedload(Poll.questions).joinedload(Question.options),
        )
        .filter(Poll.id == poll_id)
        .first()
    )


def _require_poll(db: Session, poll_id: int, *, with_relations: bool = False) -> Poll:
    poll = _poll_with_relations(db, poll_id) if with_relations else db.query(Poll).filter(Poll.id == poll_id).first()
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    return poll


def _get_form_poll(db: Session, poll_id: int) -> Poll:
    poll = _require_poll(db, poll_id)
    if not is_form(poll):
        raise HTTPException(status_code=400, detail="폼이 아닙니다.")
    return poll


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    admin = db.query(Admin).filter(Admin.username == body.username).first()
    if not admin or not verify_password(body.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenResponse(access_token=create_access_token(admin.username))


@router.get("/polls", response_model=list[PollListItem])
def list_polls(
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> list[PollListItem]:
    polls = db.query(Poll).order_by(Poll.created_at.desc()).all()
    items: list[PollListItem] = []
    for p in polls:
        cand_count = db.query(func.count(Candidate.id)).filter(Candidate.poll_id == p.id).scalar() or 0
        question_count = db.query(func.count(Question.id)).filter(Question.poll_id == p.id).scalar() or 0
        ballot_count = db.query(func.count(Ballot.id)).filter(Ballot.poll_id == p.id).scalar() or 0
        items.append(
            PollListItem(
                id=p.id,
                title=p.title,
                category=p.category,
                status=p.status,
                candidates=cand_count,
                questions=question_count,
                max_selections=p.max_selections or 3,
                poll_type=p.poll_type or "open",
                kind=p.kind or "vote",
                verify_method=p.verify_method or "pin",
                identity_mode=p.identity_mode or "secret",
                ballots=ballot_count,
                eligible=p.eligible_count,
                created_at=p.created_at,
                closes_at=p.closes_at,
                desc=p.description,
            )
        )
    return items


@router.post("/polls", response_model=PollOut, status_code=201)
def create_poll(
    body: PollCreate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> Poll:
    poll_type = body.poll_type or "open"
    kind = body.kind or "vote"
    poll = Poll(
        title=body.title,
        subtitle=body.subtitle,
        description=body.description,
        category=body.category,
        status="draft",
        closes_at=body.closes_at,
        eligible_count=0 if poll_type == "restricted" else body.eligible_count,
        max_selections=body.max_selections,
        poll_type=poll_type,
        kind=kind,
        verify_method=body.verify_method or "pin",
        identity_mode=body.identity_mode or ("identified" if kind == "form" else "secret"),
        verify_fields=(
            serialize_verify_fields(body.verify_fields)
            if poll_type == "restricted"
            else "name,email,phone"
        ),
    )
    db.add(poll)
    db.flush()
    for i, c in enumerate(body.candidates):
        db.add(
            Candidate(
                poll_id=poll.id,
                name=c.name,
                team=c.team,
                tagline=c.tagline,
                image_url=c.image_url,
                figma_url=c.figma_url,
                tint=c.tint,
                order_num=i,
            )
        )
    db.commit()
    loaded = _poll_with_relations(db, poll.id)
    assert loaded is not None
    return loaded


@router.get("/polls/{poll_id}", response_model=PollOut)
def get_poll_admin(
    poll_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> Poll:
    return _require_poll(db, poll_id, with_relations=True)


@router.patch("/polls/{poll_id}", response_model=PollOut)
def update_poll(
    poll_id: int,
    body: PollUpdate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> Poll:
    poll = _require_poll(db, poll_id, with_relations=True)
    data = body.model_dump(exclude_unset=True)
    if "verify_fields" in data and data["verify_fields"] is not None:
        data["verify_fields"] = serialize_verify_fields(data["verify_fields"])
    if data.get("status") == "active":
        if is_form(poll):
            qcount = db.query(func.count(Question.id)).filter(Question.poll_id == poll.id).scalar() or 0
            if qcount < 1:
                raise HTTPException(status_code=400, detail="문항을 1개 이상 만든 뒤 시작할 수 있습니다.")
        else:
            ccount = db.query(func.count(Candidate.id)).filter(Candidate.poll_id == poll.id).scalar() or 0
            if ccount < 2:
                raise HTTPException(status_code=400, detail="후보를 2명 이상 등록한 뒤 시작할 수 있습니다.")
    if is_form(poll) and data.get("identity_mode") == "secret":
        raise HTTPException(status_code=400, detail="폼은 기명만 지원합니다.")
    for field, value in data.items():
        setattr(poll, field, value)
    db.commit()
    notify_poll_updated(poll_id)
    loaded = _poll_with_relations(db, poll_id)
    assert loaded is not None
    return loaded


@router.delete("/polls/{poll_id}", status_code=204)
def delete_poll(
    poll_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> None:
    poll = db.query(Poll).filter(Poll.id == poll_id).first()
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    db.delete(poll)
    db.commit()


@router.post("/polls/{poll_id}/candidates", response_model=CandidateOut, status_code=201)
def add_candidate(
    poll_id: int,
    body: CandidateCreate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> Candidate:
    poll = db.query(Poll).filter(Poll.id == poll_id).first()
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    max_order = db.query(func.max(Candidate.order_num)).filter(Candidate.poll_id == poll_id).scalar() or 0
    cand = Candidate(
        poll_id=poll_id,
        name=body.name,
        team=body.team,
        tagline=body.tagline,
        image_url=body.image_url,
        figma_url=body.figma_url,
        tint=body.tint,
        order_num=max_order + 1,
    )
    db.add(cand)
    db.commit()
    db.refresh(cand)
    return cand


@router.patch("/polls/{poll_id}/candidates/{candidate_id}", response_model=CandidateOut)
def update_candidate(
    poll_id: int,
    candidate_id: int,
    body: CandidateUpdate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> Candidate:
    cand = (
        db.query(Candidate)
        .filter(Candidate.id == candidate_id, Candidate.poll_id == poll_id)
        .first()
    )
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(cand, field, value)
    db.commit()
    db.refresh(cand)
    return cand


def _add_eligible_voter_row(db: Session, poll: Poll, body: EligibleVoterCreate) -> EligibleVoter:
    if poll.poll_type != "restricted":
        raise HTTPException(status_code=400, detail="불특정 투표에는 대상자를 등록할 수 없습니다.")

    fields = parse_verify_fields(poll.verify_fields)
    values = _collect_input_values(
        fields,
        name=body.name,
        email=body.email,
        phone=body.phone,
    )
    name_norm = values.get("name") or values.get("email") or values.get("phone") or "unknown"
    email_norm = values.get("email")
    phone_norm = values.get("phone")
    display_name = (body.name or "").strip() or body.email or body.phone or "대상자"

    if email_norm:
        dup = (
            db.query(EligibleVoter)
            .filter(EligibleVoter.poll_id == poll.id, EligibleVoter.email_norm == email_norm)
            .first()
        )
        if dup:
            raise HTTPException(status_code=409, detail="이미 등록된 이메일입니다.")
    if phone_norm:
        dup = (
            db.query(EligibleVoter)
            .filter(EligibleVoter.poll_id == poll.id, EligibleVoter.phone_norm == phone_norm)
            .first()
        )
        if dup:
            raise HTTPException(status_code=409, detail="이미 등록된 전화번호입니다.")

    voter = EligibleVoter(
        poll_id=poll.id,
        name=display_name,
        email=body.email.strip() if body.email and body.email.strip() else None,
        phone=body.phone.strip() if body.phone and body.phone.strip() else None,
        name_norm=name_norm,
        email_norm=email_norm,
        phone_norm=phone_norm,
    )
    db.add(voter)
    db.flush()
    return voter


def _eligible_voter_out(
    db: Session,
    poll_id: int,
    voter: EligibleVoter,
    voters: list[EligibleVoter] | None = None,
) -> EligibleVoterOut:
    ballot = resolve_voter_ballot(db, poll_id, voter, voters)
    return EligibleVoterOut(
        id=voter.id,
        name=voter.name,
        email=voter.email,
        phone=voter.phone,
        voted=ballot is not None,
        voted_at=ballot.voted_at if ballot else None,
    )


@router.get("/polls/{poll_id}/voters", response_model=list[EligibleVoterOut])
def list_eligible_voters(
    poll_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> list[EligibleVoterOut]:
    poll = db.query(Poll).filter(Poll.id == poll_id).first()
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    voters = (
        db.query(EligibleVoter)
        .filter(EligibleVoter.poll_id == poll_id)
        .order_by(EligibleVoter.id.asc())
        .all()
    )
    return [_eligible_voter_out(db, poll_id, v, voters) for v in voters]


@router.post("/polls/{poll_id}/voters", response_model=EligibleVoterOut, status_code=201)
def add_eligible_voter(
    poll_id: int,
    body: EligibleVoterCreate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> EligibleVoterOut:
    poll = db.query(Poll).filter(Poll.id == poll_id).first()
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    voter = _add_eligible_voter_row(db, poll, body)
    db.commit()
    db.refresh(voter)
    sync_eligible_count(db, poll_id)
    notify_voters_updated(poll_id)
    notify_poll_updated(poll_id)
    return _eligible_voter_out(db, poll_id, voter)


@router.post("/polls/{poll_id}/voters/bulk", response_model=list[EligibleVoterOut], status_code=201)
def add_eligible_voters_bulk(
    poll_id: int,
    body: EligibleVoterBulkCreate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> list[EligibleVoterOut]:
    poll = db.query(Poll).filter(Poll.id == poll_id).first()
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    created: list[EligibleVoter] = []
    for item in body.voters:
        created.append(_add_eligible_voter_row(db, poll, item))
    db.commit()
    for voter in created:
        db.refresh(voter)
    sync_eligible_count(db, poll_id)
    notify_voters_updated(poll_id)
    notify_poll_updated(poll_id)
    return [_eligible_voter_out(db, poll_id, v) for v in created]


@router.delete("/polls/{poll_id}/voters/{voter_id}/vote", response_model=RevokeVoterVoteResponse)
def revoke_voter_vote(
    poll_id: int,
    voter_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> RevokeVoterVoteResponse:
    poll = db.query(Poll).filter(Poll.id == poll_id).first()
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    if poll.poll_type != "restricted":
        raise HTTPException(status_code=400, detail="불특정 투표는 대상자별 투표 취소를 지원하지 않습니다.")

    voter = (
        db.query(EligibleVoter)
        .filter(EligibleVoter.id == voter_id, EligibleVoter.poll_id == poll_id)
        .first()
    )
    if not voter:
        raise HTTPException(status_code=404, detail="Voter not found")

    ballot = resolve_voter_ballot(db, poll_id, voter)
    if not ballot:
        raise HTTPException(status_code=404, detail="이 대상자의 투표 내역이 없습니다.")

    db.delete(ballot)
    db.commit()
    notify_results_updated(poll_id)
    notify_voters_updated(poll_id)
    return RevokeVoterVoteResponse()


@router.delete("/polls/{poll_id}/voters/{voter_id}", status_code=204)
def delete_eligible_voter(
    poll_id: int,
    voter_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> None:
    voter = (
        db.query(EligibleVoter)
        .filter(EligibleVoter.id == voter_id, EligibleVoter.poll_id == poll_id)
        .first()
    )
    if not voter:
        raise HTTPException(status_code=404, detail="Voter not found")
    ballot = resolve_voter_ballot(db, poll_id, voter)
    if ballot:
        db.delete(ballot)
    db.delete(voter)
    db.commit()
    sync_eligible_count(db, poll_id)
    notify_voters_updated(poll_id)
    if ballot:
        notify_results_updated(poll_id)
    notify_poll_updated(poll_id)


@router.delete("/polls/{poll_id}/candidates/{candidate_id}", status_code=204)
def delete_candidate(
    poll_id: int,
    candidate_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> None:
    cand = (
        db.query(Candidate)
        .filter(Candidate.id == candidate_id, Candidate.poll_id == poll_id)
        .first()
    )
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate not found")
    delete_media_file(settings, cand.image_url)
    db.delete(cand)
    db.commit()


@router.post("/polls/{poll_id}/reset", response_model=ResetVotesResponse)
def reset_poll_votes(
    poll_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> ResetVotesResponse:
    poll = db.query(Poll).filter(Poll.id == poll_id).first()
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    ballots = db.query(Ballot).filter(Ballot.poll_id == poll_id).all()
    count = len(ballots)
    for ballot in ballots:
        db.delete(ballot)
    db.commit()
    notify_results_updated(poll_id)
    return ResetVotesResponse(deleted_ballots=count)


@router.get("/polls/{poll_id}/results", response_model=ResultsOut)
def poll_results(
    poll_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> ResultsOut:
    poll = _require_poll(db, poll_id)
    if is_form(poll):
        raise HTTPException(status_code=400, detail="폼 결과는 /admin/polls/{id}/form-results 를 사용하세요.")
    return get_results(db, poll_id, poll.eligible_count)


@router.get("/polls/{poll_id}/results/csv")
def poll_results_csv(
    poll_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> PlainTextResponse:
    poll = _require_poll(db, poll_id)
    if is_form(poll):
        raise HTTPException(status_code=400, detail="폼 CSV는 /admin/polls/{id}/form-results/csv 를 사용하세요.")
    content = results_csv(db, poll_id, poll.eligible_count)
    return PlainTextResponse(content, media_type="text/csv")


@router.get("/polls/{poll_id}/form-results", response_model=FormResultsOut)
def poll_form_results(
    poll_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> FormResultsOut:
    poll = _get_form_poll(db, poll_id)
    return get_form_results(db, poll, include_responses=True)


@router.get("/polls/{poll_id}/form-results/csv")
def poll_form_results_csv(
    poll_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> PlainTextResponse:
    poll = _get_form_poll(db, poll_id)
    return PlainTextResponse(form_results_csv(db, poll), media_type="text/csv")


@router.post("/polls/{poll_id}/questions", response_model=QuestionOut, status_code=201)
def add_question(
    poll_id: int,
    body: QuestionCreate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> Question:
    poll = _get_form_poll(db, poll_id)
    max_order = db.query(func.max(Question.order_num)).filter(Question.poll_id == poll.id).scalar() or 0
    q = Question(
        poll_id=poll.id,
        title=body.title,
        help_text=body.help_text,
        type=body.type,
        required=body.required,
        order_num=body.order_num if body.order_num is not None else max_order + 1,
        scale_min=body.scale_min,
        scale_max=body.scale_max,
    )
    db.add(q)
    db.flush()
    for i, opt in enumerate(body.options):
        db.add(QuestionOption(question_id=q.id, label=opt.label, order_num=i))
    db.commit()
    return (
        db.query(Question)
        .options(joinedload(Question.options))
        .filter(Question.id == q.id)
        .one()
    )


@router.patch("/polls/{poll_id}/questions/{question_id}", response_model=QuestionOut)
def update_question(
    poll_id: int,
    question_id: int,
    body: QuestionUpdate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> Question:
    _get_form_poll(db, poll_id)
    q = (
        db.query(Question)
        .options(joinedload(Question.options))
        .filter(Question.id == question_id, Question.poll_id == poll_id)
        .first()
    )
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(q, field, value)
    db.commit()
    db.refresh(q)
    return q


@router.delete("/polls/{poll_id}/questions/{question_id}", status_code=204)
def delete_question(
    poll_id: int,
    question_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> None:
    _get_form_poll(db, poll_id)
    q = db.query(Question).filter(Question.id == question_id, Question.poll_id == poll_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    db.delete(q)
    db.commit()


@router.post("/polls/{poll_id}/questions/{question_id}/options", response_model=QuestionOptionOut, status_code=201)
def add_question_option(
    poll_id: int,
    question_id: int,
    body: QuestionOptionCreate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> QuestionOption:
    _get_form_poll(db, poll_id)
    q = db.query(Question).filter(Question.id == question_id, Question.poll_id == poll_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    max_order = db.query(func.max(QuestionOption.order_num)).filter(QuestionOption.question_id == q.id).scalar() or 0
    opt = QuestionOption(question_id=q.id, label=body.label, order_num=max_order + 1)
    db.add(opt)
    db.commit()
    db.refresh(opt)
    return opt


@router.patch("/polls/{poll_id}/questions/{question_id}/options/{option_id}", response_model=QuestionOptionOut)
def update_question_option(
    poll_id: int,
    question_id: int,
    option_id: int,
    body: QuestionOptionUpdate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> QuestionOption:
    _get_form_poll(db, poll_id)
    opt = (
        db.query(QuestionOption)
        .join(Question)
        .filter(
            QuestionOption.id == option_id,
            QuestionOption.question_id == question_id,
            Question.poll_id == poll_id,
        )
        .first()
    )
    if not opt:
        raise HTTPException(status_code=404, detail="Option not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(opt, field, value)
    db.commit()
    db.refresh(opt)
    return opt


@router.delete("/polls/{poll_id}/questions/{question_id}/options/{option_id}", status_code=204)
def delete_question_option(
    poll_id: int,
    question_id: int,
    option_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
) -> None:
    _get_form_poll(db, poll_id)
    opt = (
        db.query(QuestionOption)
        .join(Question)
        .filter(
            QuestionOption.id == option_id,
            QuestionOption.question_id == question_id,
            Question.poll_id == poll_id,
        )
        .first()
    )
    if not opt:
        raise HTTPException(status_code=404, detail="Option not found")
    db.delete(opt)
    db.commit()


@router.post("/upload/presign", response_model=PresignResponse)
def presign_upload(
    body: PresignRequest,
    _admin: Admin = Depends(get_current_admin),
) -> PresignResponse:
    if not settings.s3_enabled:
        raise HTTPException(status_code=503, detail="S3 upload is not configured")
    content_type = body.content_type if body.content_type.startswith("image/") else "image/jpeg"
    result = create_presigned_upload(settings, body.filename, content_type)
    return PresignResponse(**result)


@router.post("/upload/image", response_model=UploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    _admin: Admin = Depends(get_current_admin),
) -> UploadResponse:
    if settings.s3_enabled:
        raise HTTPException(
            status_code=400,
            detail="Use POST /api/admin/upload/presign for S3 uploads",
        )
    media = settings.media_path
    media.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "img.jpg").suffix or ".jpg"
    name = f"{uuid.uuid4().hex}{ext}"
    dest = media / name
    content = await file.read()
    dest.write_bytes(content)
    return UploadResponse(url=f"/media/{name}")
