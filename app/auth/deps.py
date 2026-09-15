import secrets

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.jwt import decode_token, hash_password
from app.config import get_settings
from app.database import get_db
from app.models import Admin, Poll
from app.services.keycloak import decode_keycloak_token, has_app_access

security = HTTPBearer(auto_error=False)
settings = get_settings()


def owner_key(admin: Admin) -> str:
    if admin.idp_sub:
        return admin.idp_sub
    return f"local:{admin.username}"


def can_manage_poll(admin: Admin, poll: Poll) -> bool:
    if poll.owner_id:
        return poll.owner_id == owner_key(admin)
    # Legacy rows without an owner stay with local login, not company SSO users.
    return admin.idp_sub is None


def _upsert_oidc_admin(db: Session, payload: dict) -> Admin:
    sub = str(payload.get("sub"))
    base_username = str(payload.get("preferred_username") or payload.get("email") or sub)
    admin = db.query(Admin).filter(Admin.idp_sub == sub).first()
    if admin:
        return admin
    username = base_username
    existing = db.query(Admin).filter(Admin.username == username).first()
    if existing:
        username = f"{base_username}#{sub[:8]}"
    admin = Admin(
        username=username,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        idp_sub=sub,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _admin_from_bearer(token: str, db: Session) -> Admin | None:
    mode = settings.auth_mode if settings.auth_mode in ("local", "oidc", "both") else "both"
    if mode in ("oidc", "both") and settings.keycloak_enabled:
        try:
            payload = decode_keycloak_token(token)
            if not has_app_access(payload):
                raise HTTPException(status_code=403, detail="이 앱에 접근 권한이 없습니다.")
            return _upsert_oidc_admin(db, payload)
        except HTTPException as exc:
            if exc.status_code != 401 or mode == "oidc":
                raise
    if mode in ("local", "both"):
        username = decode_token(token)
        if username:
            admin = db.query(Admin).filter(Admin.username == username).first()
            if admin:
                return admin
    return None


def get_current_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> Admin:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    admin = _admin_from_bearer(creds.credentials, db)
    if not admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return admin


def get_current_admin_from_token(
    token: str = Query(..., min_length=10),
    db: Session = Depends(get_db),
) -> Admin:
    admin = _admin_from_bearer(token, db)
    if not admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return admin
