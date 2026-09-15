import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(subject: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": subject, "exp": expire}, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        return str(sub) if sub else None
    except JWTError:
        return None


def create_voter_token(poll_id: int, voter_id: int) -> str:
    expire = datetime.now(UTC) + timedelta(days=7)
    return jwt.encode(
        {"typ": "voter", "poll_id": poll_id, "voter_id": voter_id, "exp": expire},
        settings.secret_key,
        algorithm=ALGORITHM,
    )


def decode_voter_token(token: str) -> tuple[int, int] | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        if payload.get("typ") != "voter":
            return None
        poll_id = payload.get("poll_id")
        voter_id = payload.get("voter_id")
        if poll_id is None or voter_id is None:
            return None
        return int(poll_id), int(voter_id)
    except JWTError:
        return None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_ballot_token(poll_id: int) -> str:
    expire = datetime.now(UTC) + timedelta(days=7)
    return jwt.encode(
        {"typ": "ballot", "poll_id": poll_id, "nonce": secrets.token_hex(16), "exp": expire},
        settings.secret_key,
        algorithm=ALGORITHM,
    )


def decode_ballot_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        if payload.get("typ") != "ballot":
            return None
        poll_id = payload.get("poll_id")
        return int(poll_id) if poll_id is not None else None
    except JWTError:
        return None
