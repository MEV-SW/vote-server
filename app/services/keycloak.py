import json
import time
import urllib.error
import urllib.request

from fastapi import HTTPException
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()

_jwks_cache: dict = {"data": None, "exp": 0.0}


def keycloak_issuer() -> str:
    return (settings.keycloak_issuer or "").rstrip("/")


def _load_jwks() -> dict:
    now = time.time()
    if _jwks_cache["data"] and now < _jwks_cache["exp"]:
        return _jwks_cache["data"]
    url = f"{keycloak_issuer()}/protocol/openid-connect/certs"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="Keycloak 인증 서버에 연결할 수 없습니다.") from exc
    _jwks_cache["data"] = data
    _jwks_cache["exp"] = now + 300
    return data


def decode_keycloak_token(token: str) -> dict:
    if not settings.keycloak_enabled:
        raise HTTPException(status_code=503, detail="Keycloak이 설정되지 않았습니다.")
    try:
        payload = jwt.decode(
            token,
            _load_jwks(),
            algorithms=["RS256"],
            issuer=keycloak_issuer(),
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="회사 계정 인증이 유효하지 않습니다.") from exc
    azp = payload.get("azp")
    aud = payload.get("aud")
    client_id = settings.keycloak_client_id
    if azp != client_id and aud != client_id and client_id not in (aud if isinstance(aud, list) else [aud]):
        raise HTTPException(status_code=401, detail="회사 계정 인증이 유효하지 않습니다.")
    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="회사 계정 인증이 유효하지 않습니다.")
    return payload


def has_admin_role(payload: dict) -> bool:
    role = (settings.keycloak_admin_role or "").strip()
    if not role:
        return False
    realm_roles = payload.get("realm_access", {}).get("roles") or []
    if role in realm_roles:
        return True
    client_id = settings.keycloak_client_id or ""
    client_roles = (payload.get("resource_access") or {}).get(client_id, {}).get("roles") or []
    return role in client_roles


def has_app_access(payload: dict) -> bool:
    """Company login is enough unless KEYCLOAK_ADMIN_ROLE is set as an access gate."""
    role = (settings.keycloak_admin_role or "").strip()
    if not role:
        return True
    return has_admin_role(payload)


def display_name(payload: dict) -> str:
    return (
        payload.get("name")
        or payload.get("preferred_username")
        or payload.get("email")
        or "직원"
    )


def auth_config() -> dict:
    mode = settings.auth_mode if settings.auth_mode in ("local", "oidc", "both") else "both"
    oidc_on = mode in ("oidc", "both") and settings.keycloak_enabled
    local_on = mode in ("local", "both")
    return {
        "mode": mode,
        "local_enabled": local_on,
        "oidc_enabled": oidc_on,
        "issuer": settings.keycloak_issuer.rstrip("/") if oidc_on and settings.keycloak_issuer else None,
        "client_id": settings.keycloak_client_id if oidc_on else None,
    }
