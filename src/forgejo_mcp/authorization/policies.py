from typing import Annotated

from fastapi import Depends, HTTPException, status

from forgejo_mcp.auth.session import CsrfSession, get_current_session
from forgejo_mcp.db.models import AccountRole, Session


async def require_ready_account(
    current: Annotated[Session, Depends(get_current_session)],
) -> Session:
    if current.account.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "password change required")
    return current


ReadySession = Annotated[Session, Depends(require_ready_account)]


async def require_admin(current: ReadySession) -> Session:
    if current.account.role != AccountRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin access required")
    return current


AdminSession = Annotated[Session, Depends(require_admin)]


async def require_admin_csrf(current: CsrfSession) -> Session:
    if current.account.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "password change required")
    if current.account.role != AccountRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin access required")
    return current


AdminCsrfSession = Annotated[Session, Depends(require_admin_csrf)]


async def require_user(current: ReadySession) -> Session:
    if current.account.role != AccountRole.USER or current.account.user_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user access required")
    return current


UserSession = Annotated[Session, Depends(require_user)]


async def require_user_csrf(current: CsrfSession) -> Session:
    if current.account.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "password change required")
    if current.account.role != AccountRole.USER or current.account.user_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user access required")
    return current


UserCsrfSession = Annotated[Session, Depends(require_user_csrf)]
