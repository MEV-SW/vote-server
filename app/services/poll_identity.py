from app.models import Poll

PollKind = str
VerifyMethod = str
IdentityMode = str


def resolve_identity_mode(kind: str, poll_type: str, identity_mode: str | None) -> str:
    if kind == "form":
        return "identified"
    if poll_type == "open":
        return "secret"
    if identity_mode in ("identified", "secret"):
        return identity_mode
    return "identified"


def resolve_verify_method(poll_type: str, verify_method: str | None) -> str:
    if poll_type != "restricted":
        return "pin"
    if verify_method == "sso":
        return "sso"
    return "pin"


def is_secret(poll: Poll) -> bool:
    return (poll.identity_mode or "secret") == "secret"


def is_form(poll: Poll) -> bool:
    return (poll.kind or "vote") == "form"


def is_sso(poll: Poll) -> bool:
    return poll.poll_type == "restricted" and (poll.verify_method or "pin") == "sso"
