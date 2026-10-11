import hashlib
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request
from fastapi.security.utils import get_authorization_scheme_param

from app.schemas.models import Scope


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str
    scope: Scope

    @property
    def scope_hash(self):
        return hashlib.sha256(self.scope.model_dump_json().encode()).hexdigest()


def principal_from_token(token: str, settings) -> Principal:
    # Tokens are server configured identities, never user-supplied scope claims.
    entries = [
        (settings.api_auth_token, "netops-engineer", "engineer"),
        (settings.api_admin_token, "netops-admin", "admin"),
    ]
    for secret, user, role in entries:
        expected = secret.get_secret_value()
        if expected and secrets.compare_digest(token, expected):
            return Principal(user, role, Scope())
    raise HTTPException(
        status_code=401, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"}
    )


async def current_principal(request: Request):
    scheme, token = get_authorization_scheme_param(request.headers.get("Authorization"))
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal_from_token(token, request.app.state.settings)


async def admin_principal(request: Request):
    principal = await current_principal(request)
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator role required")
    return principal
