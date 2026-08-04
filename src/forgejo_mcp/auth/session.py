import hmac
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status

from forgejo_mcp.auth.tokens import hash_token
from forgejo_mcp.db.dependencies import DbSession
from forgejo_mcp.db.models import RecordStatus, Session
from forgejo_mcp.db.repositories import SessionRepository

SESSION_COOKIE = "fmcp_session"
CSRF_COOKIE = "fmcp_csrf"
CSRF_HEADER = "X-CSRF-Token"


async def get_current_session(
    db: DbSession,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> Session:
    if session_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")

    record = await SessionRepository(db).by_token_hash(hash_token(session_token))
    now = datetime.now(UTC)
    if (
        record is None
        or record.revoked_at is not None
        or record.expires_at <= now
        or record.account.status != RecordStatus.ACTIVE
        or (record.account.user is not None and record.account.user.status != RecordStatus.ACTIVE)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
    return record


CurrentSession = Annotated[Session, Depends(get_current_session)]


async def require_csrf(
    current: CurrentSession,
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
    csrf_header: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
) -> Session:
    if (
        csrf_cookie is None
        or csrf_header is None
        or not hmac.compare_digest(csrf_cookie, csrf_header)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")
    if not hmac.compare_digest(hash_token(csrf_header), current.csrf_token_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")
    return current


CsrfSession = Annotated[Session, Depends(require_csrf)]
