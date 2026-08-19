"""Auth dependencies.

The forum service is stateless with respect to users: it has no users
collection. It trusts the JWTs signed by the api-service (shared JWT_SECRET)
and builds a lightweight user dict straight from the token payload. That is
the point of stateless JWTs between microservices — no cross-service lookup.
"""
from enum import Enum

import jwt
from fastapi import Depends, HTTPException, status ,Query, WebSocketException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

_bearer = HTTPBearer(auto_error=True)


class Role(str, Enum):
    USER = "USER"
    AGENT = "AGENT"
    ADMIN = "ADMIN"


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    try:
        payload = jwt.decode(
            creds.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from None

    user_id = payload.get("sub")
    role = payload.get("role")
    if not user_id or role not in {r.value for r in Role}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload"
        )
    return {"id": user_id, "role": role}


def require_roles(*roles: Role):
    """Dependency factory enforcing that the caller has one of ``roles``."""

    allowed = {r.value for r in roles}

    async def _checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return _checker


# NEW: Add this at the bottom of the file
async def get_ws_user(token: str = Query(...)) -> dict:
    """Authenticates WebSockets via query parameter instead of headers."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid or expired token",
        )

    user_id = payload.get("sub")
    role = payload.get("role")
    if not user_id or role not in {r.value for r in Role}:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token payload"
        )
    return {"id": user_id, "role": role}