"""Dashboard authentication and role handling."""

from app.auth.dependencies import (
    CurrentUser,
    NotAuthenticated,
    NotAuthorised,
    can_access_contact,
    get_current_user,
    get_optional_user,
    login_redirect,
    require_admin,
    require_full_access,
)
from app.auth.session import COOKIE_NAME, cookie_params, issue_session, read_session

__all__ = [
    "CurrentUser",
    "NotAuthenticated",
    "NotAuthorised",
    "get_current_user",
    "get_optional_user",
    "require_admin",
    "require_full_access",
    "can_access_contact",
    "login_redirect",
    "COOKIE_NAME",
    "issue_session",
    "read_session",
    "cookie_params",
]
