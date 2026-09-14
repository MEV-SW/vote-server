from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.poll_identity import resolve_identity_mode, resolve_verify_method
from app.services.verify_fields import parse_verify_fields, validate_verify_fields_list

PollType = Literal["open", "restricted"]
PollKind = Literal["vote", "form"]
VerifyMethod = Literal["pin", "sso"]
IdentityMode = Literal["identified", "secret"]
VerifyField = Literal["name", "email", "phone"]
QuestionType = Literal["short_text", "long_text", "single_choice", "multi_choice", "scale"]


class CandidateOut(BaseModel):
    id: int
    name: str
    team: str | None = None
    tagline: str | None = None
    image_url: str | None = None
    figma_url: str | None = None
    tint: int = 256

    model_config = {"from_attributes": True}


class QuestionOptionOut(BaseModel):
    id: int
    label: str
    order_num: int = 0

    model_config = {"from_attributes": True}


class QuestionOut(BaseModel):
    id: int
    title: str
    help_text: str | None = None
    type: QuestionType
    required: bool = True
    order_num: int = 0
    scale_min: int = 1
    scale_max: int = 5
    options: list[QuestionOptionOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class QuestionOptionCreate(BaseModel):
    label: str = Field(min_length=1, max_length=300)


class QuestionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    help_text: str | None = None
    type: QuestionType
    required: bool = True
    order_num: int | None = None
    scale_min: int = Field(default=1, ge=1, le=10)
    scale_max: int = Field(default=5, ge=2, le=10)
    options: list[QuestionOptionCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _options_for_choice(self) -> "QuestionCreate":
        if self.type in ("single_choice", "multi_choice") and len(self.options) < 2:
            raise ValueError("객관식 문항은 보기가 2개 이상 필요합니다.")
        if self.scale_max <= self.scale_min:
            raise ValueError("척도 최댓값은 최솟값보다 커야 합니다.")
        return self


class QuestionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    help_text: str | None = None
    required: bool | None = None
    order_num: int | None = None
    scale_min: int | None = Field(default=None, ge=1, le=10)
    scale_max: int | None = Field(default=None, ge=2, le=10)


class QuestionOptionUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=300)
    order_num: int | None = None


class PollPublicOut(BaseModel):
    id: int
    title: str
    subtitle: str | None = None
    description: str | None = None
    category: str
    status: str
    closes_at: datetime | None = None
    max_selections: int = 3
    kind: PollKind = "vote"
    poll_type: PollType = "open"
    verify_method: VerifyMethod = "pin"
    identity_mode: IdentityMode = "secret"
    candidates: list[CandidateOut] = Field(default_factory=list)
    questions: list[QuestionOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class PollOut(BaseModel):
    id: int
    title: str
    subtitle: str | None = None
    description: str | None = None
    category: str
    status: str
    closes_at: datetime | None = None
    eligible_count: int
    max_selections: int = 3
    poll_type: PollType = "open"
    verify_fields: list[VerifyField] = Field(default_factory=lambda: ["name", "email", "phone"])
    kind: PollKind = "vote"
    verify_method: VerifyMethod = "pin"
    identity_mode: IdentityMode = "secret"
    candidates: list[CandidateOut] = Field(default_factory=list)
    questions: list[QuestionOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}

    @field_validator("verify_fields", mode="before")
    @classmethod
    def _parse_verify_fields(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return parse_verify_fields(v)  # type: ignore[return-value]
        return v  # type: ignore[return-value]


class VoteEntry(BaseModel):
    rank: int = Field(ge=1, le=5)
    candidate_id: int


class VoteSubmit(BaseModel):
    fingerprint: str = Field(min_length=8, max_length=64)
    voter_token: str | None = None
    ballot_token: str | None = None
    votes: list[VoteEntry] = Field(min_length=1, max_length=5)


class AnswerSubmit(BaseModel):
    question_id: int
    text_value: str | None = Field(default=None, max_length=4000)
    scale_value: int | None = None
    option_ids: list[int] = Field(default_factory=list)


class FormSubmit(BaseModel):
    fingerprint: str = Field(min_length=8, max_length=64)
    voter_token: str | None = None
    answers: list[AnswerSubmit] = Field(min_length=1)


class VerifyVoterRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    pin: str | None = Field(default=None, min_length=4, max_length=4)


class VerifySsoRequest(BaseModel):
    access_token: str = Field(min_length=20)


class VerifyVoterResponse(BaseModel):
    verified: bool = False
    voter_token: str | None = None
    ballot_token: str | None = None
    voter_name: str
    already_voted: bool = False
    pin_required: bool = False
    pin_setup: bool = False
    identity_mode: IdentityMode = "identified"


class CheckResponse(BaseModel):
    voted: bool
    votes: list[VoteEntry] | None = None
    answers: list[AnswerSubmit] | None = None


class PollPublicListItem(BaseModel):
    id: int
    title: str
    category: str
    status: str
    candidates: int
    questions: int = 0
    max_selections: int = 3
    poll_type: PollType = "open"
    kind: PollKind = "vote"
    identity_mode: IdentityMode = "secret"
    ballots: int
    closes_at: datetime | None = None
    desc: str | None = None


class PollListItem(BaseModel):
    id: int
    title: str
    category: str
    status: str
    candidates: int
    questions: int = 0
    max_selections: int = 3
    poll_type: PollType = "open"
    kind: PollKind = "vote"
    verify_method: VerifyMethod = "pin"
    identity_mode: IdentityMode = "secret"
    ballots: int
    eligible: int
    created_at: datetime
    closes_at: datetime | None = None
    desc: str | None = None


class CandidateCreate(BaseModel):
    name: str
    team: str | None = None
    tagline: str | None = None
    image_url: str | None = None
    figma_url: str | None = None
    tint: int = 256


class PollCreate(BaseModel):
    title: str
    subtitle: str | None = None
    description: str | None = None
    category: str = "기타"
    closes_at: datetime | None = None
    eligible_count: int = 312
    max_selections: int = Field(default=3, ge=1, le=5)
    poll_type: PollType = "open"
    verify_fields: list[VerifyField] = Field(default_factory=lambda: ["email"])
    kind: PollKind = "vote"
    verify_method: VerifyMethod = "pin"
    identity_mode: IdentityMode | None = None
    candidates: list[CandidateCreate] = Field(default_factory=list)

    @field_validator("verify_fields")
    @classmethod
    def _validate_verify_fields(cls, v: list[str]) -> list[str]:
        return validate_verify_fields_list(v)  # type: ignore[return-value]

    @model_validator(mode="after")
    def _resolve_kind(self) -> "PollCreate":
        self.verify_method = resolve_verify_method(self.poll_type, self.verify_method)
        self.identity_mode = resolve_identity_mode(self.kind, self.poll_type, self.identity_mode)
        if self.kind == "vote" and len(self.candidates) < 2:
            raise ValueError("투표는 후보가 2명 이상 필요합니다.")
        if self.kind == "form":
            self.candidates = []
            self.identity_mode = "identified"
        return self


class PollUpdate(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    description: str | None = None
    category: str | None = None
    status: str | None = None
    closes_at: datetime | None = None
    eligible_count: int | None = None
    max_selections: int | None = Field(default=None, ge=1, le=5)
    poll_type: PollType | None = None
    verify_fields: list[VerifyField] | None = None
    verify_method: VerifyMethod | None = None
    identity_mode: IdentityMode | None = None

    @field_validator("verify_fields")
    @classmethod
    def _validate_verify_fields(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return validate_verify_fields_list(v)  # type: ignore[return-value]


class EligibleVoterOut(BaseModel):
    id: int
    name: str
    email: str | None = None
    phone: str | None = None
    voted: bool = False
    voted_at: datetime | None = None

    model_config = {"from_attributes": True}


class RevokeVoterVoteResponse(BaseModel):
    revoked: bool = True


class EligibleVoterCreate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)


class EligibleVoterBulkCreate(BaseModel):
    voters: list[EligibleVoterCreate] = Field(min_length=1)


class CandidateUpdate(BaseModel):
    name: str | None = None
    team: str | None = None
    tagline: str | None = None
    image_url: str | None = None
    figma_url: str | None = None
    tint: int | None = None


class ResultRow(BaseModel):
    candidate_id: int
    name: str
    team: str | None = None
    tagline: str | None = None
    tint: int
    r1: int
    r2: int
    r3: int
    r4: int = 0
    r5: int = 0
    score: int


class ResultsOut(BaseModel):
    total_ballots: int
    eligible_count: int
    participation_rate: float
    rows: list[ResultRow]


class FormOptionCount(BaseModel):
    option_id: int
    label: str
    count: int


class FormQuestionSummary(BaseModel):
    question_id: int
    title: str
    type: QuestionType
    required: bool
    response_count: int
    option_counts: list[FormOptionCount] = Field(default_factory=list)
    scale_avg: float | None = None
    scale_counts: dict[int, int] = Field(default_factory=dict)
    texts: list[str] = Field(default_factory=list)


class FormAnswerOut(BaseModel):
    question_id: int
    title: str
    type: QuestionType
    text_value: str | None = None
    scale_value: int | None = None
    option_labels: list[str] = Field(default_factory=list)


class FormResponseOut(BaseModel):
    ballot_id: int
    submitted_at: datetime
    voter_name: str | None = None
    voter_email: str | None = None
    answers: list[FormAnswerOut]


class FormResultsOut(BaseModel):
    total_responses: int
    eligible_count: int
    participation_rate: float
    questions: list[FormQuestionSummary]
    responses: list[FormResponseOut] = Field(default_factory=list)


class AuthConfigOut(BaseModel):
    mode: str
    local_enabled: bool
    oidc_enabled: bool
    issuer: str | None = None
    client_id: str | None = None


def poll_to_list_counts(p: Any, cand_count: int, question_count: int, ballot_count: int) -> dict:
    return {
        "kind": getattr(p, "kind", None) or "vote",
        "verify_method": getattr(p, "verify_method", None) or "pin",
        "identity_mode": getattr(p, "identity_mode", None) or "secret",
        "candidates": cand_count,
        "questions": question_count,
        "ballots": ballot_count,
    }
