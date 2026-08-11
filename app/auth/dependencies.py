"""Authentication and role dependencies for the dashboard.

Three roles:

    ADMIN   sees everything and may change settings and manage logins
    VIEWER  sees everything, read-only
    USER    sees only the WhatsApp number its account is linked to

The USER restriction is enforced by ``CurrentUser.scope`` -- a wa_id that the
repository layer applies inside the SQL query. A view that forgets to pass it
still cannot leak another contact's rows, because the scoped helpers require it.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import COOKIE_NAME, read_session
from app.db.base import get_db
from app.db.models import User, UserRole

logger = logging.getLogger("app.auth.dependencies")


class NotAuthenticated(Exception):
    """Raised when a request has no valid session. Handled as a redirect to login."""

    def __init__(self, next_url: str = "/"):
        self.next_url = next_url
        super().__init__("Not authenticated")


class NotAuthorised(Exception):
    """Raised when a signed-in user lacks the role for a page."""

    def __init__(self, message: str = "You do not have access to that page."):
        self.message = message
        super().__init__(message)


@dataclass
class CurrentUser:
    """The signed-in account, with its data scope resolved."""

    id: int
    username: str
    name: str
    role: UserRole
    wa_id: Optional[str]

    @property
    def scope(self) -> Optional[str]:
        """The wa_id this account is limited to, or ``None`` for unrestricted.

        Pass this straight into the repository helpers' ``wa_id_scope``.
        """
        return None if self.role.sees_everything else self.wa_id

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN

    @property
    def is_restricted(self) -> bool:
        """True when this account only sees one WhatsApp number."""
        return not self.role.sees_everything

    @classmethod
    def from_model(cls, user: User) -> "CurrentUser":
        return cls(
            id=user.id,
            username=user.username,
            name=user.name,
            role=user.role_enum,
            wa_id=user.wa_id,
        )


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """Resolves the signed-in account.

    Raises:
        NotAuthenticated: If the cookie is missing, invalid, or the account no
            longer exists or has been deactivated.
    """
    user_id = read_session(request.cookies.get(COOKIE_NAME))
    if user_id is None:
        raise NotAuthenticated(next_url=request.url.path)

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        logger.info(
            "Session referenced a missing or deactivated account.",
            extra={"event": "session_user_invalid", "user_id": user_id},
        )
        raise NotAuthenticated(next_url=request.url.path)

    # A USER-role account with no linked number would see everything, which is
    # exactly backwards. Refuse it rather than fail open.
    if user.role_enum is UserRole.USER and not user.wa_id:
        logger.error(
            f"User account '{user.username}' has no linked WhatsApp number; denying access.",
            extra={"event": "user_scope_missing", "username": user.username},
        )
        raise NotAuthorised(
            "Your account is not linked to a WhatsApp number yet. Ask an administrator to set one."
        )

    return CurrentUser.from_model(user)


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[CurrentUser]:
    """Resolves the signed-in account, or ``None``. Used by the login page."""
    try:
        return await get_current_user(request, db)
    except (NotAuthenticated, NotAuthorised):
        return None


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Allows administrators only."""
    if not user.is_admin:
        logger.warning(
            f"'{user.username}' ({user.role.value}) attempted an admin-only action.",
            extra={"event": "authorisation_denied", "username": user.username},
        )
        raise NotAuthorised("Only administrators can change settings or manage logins.")
    return user


async def require_full_access(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Allows administrators and viewers -- anyone who may see every contact."""
    if user.is_restricted:
        raise NotAuthorised("Your account can only see its own reports.")
    return user


def can_access_contact(user: CurrentUser, wa_id: str) -> bool:
    """True when this account may view a given contact."""
    return not user.is_restricted or user.wa_id == wa_id


def login_redirect(next_url: str = "/") -> RedirectResponse:
    """Redirects to the login page, remembering where the user was headed."""
    from urllib.parse import quote

    target = "/login"
    if next_url and next_url not in ("/", "/login"):
        target = f"/login?next={quote(next_url, safe='')}"
    return RedirectResponse(target, status_code=303)
