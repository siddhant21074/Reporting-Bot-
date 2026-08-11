"""Data access for dashboard logins and the audit trail."""

import logging
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.db.models import AuditLog, User, UserRole, utcnow

logger = logging.getLogger("app.repositories.users")


async def get_user(db: AsyncSession, user_id: int) -> Optional[User]:
    """Returns one login by id."""
    return await db.get(User, user_id)


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    """Returns one login by username, case-insensitively."""
    result = await db.execute(select(User).where(func.lower(User.username) == username.strip().lower()))
    return result.scalar_one_or_none()


async def get_user_for_wa_id(db: AsyncSession, wa_id: str) -> Optional[User]:
    """Returns the USER-role login linked to a WhatsApp number, if one exists."""
    result = await db.execute(
        select(User).where(User.wa_id == wa_id, User.role == UserRole.USER)
    )
    return result.scalars().first()


async def list_users(db: AsyncSession) -> List[User]:
    """Returns every login, administrators first."""
    result = await db.execute(select(User).order_by(User.role, User.username))
    return list(result.scalars().all())


async def count_admins(db: AsyncSession, exclude_id: Optional[int] = None) -> int:
    """Counts active administrators, optionally ignoring one account.

    Used to refuse the change that would lock everyone out.
    """
    query = select(func.count()).select_from(User).where(
        User.role == UserRole.ADMIN, User.is_active.is_(True)
    )
    if exclude_id is not None:
        query = query.where(User.id != exclude_id)
    return int((await db.execute(query)).scalar_one())


async def authenticate(db: AsyncSession, username: str, password: str) -> Optional[User]:
    """Checks a login.

    Returns the user on success, ``None`` otherwise. The password is verified
    even when the account is unknown, so a missing username and a wrong password
    take the same amount of time.
    """
    user = await get_user_by_username(db, username)

    stored_hash = user.password_hash if user else "$2b$12$" + "." * 53
    password_ok = verify_password(password, stored_hash)

    if not user or not password_ok or not user.is_active:
        logger.warning(
            f"Failed login for '{username}'.",
            extra={"event": "login_failed", "username": username},
        )
        return None

    user.last_login_at = utcnow()
    await db.flush()
    logger.info(
        f"'{user.username}' signed in as {user.role_enum.value}.",
        extra={"event": "login_success", "username": user.username, "role": user.role_enum.value},
    )
    return user


async def create_user(
    db: AsyncSession,
    username: str,
    password: str,
    role: UserRole,
    display_name: Optional[str] = None,
    wa_id: Optional[str] = None,
    created_by: Optional[str] = None,
) -> User:
    """Creates a login.

    Args:
        db: Session.
        username: Unique, case-insensitive.
        password: Plaintext; hashed before storage.
        role: ADMIN, VIEWER or USER.
        display_name: Optional friendly name.
        wa_id: Required for the USER role -- the number the account may see.
        created_by: Username of the administrator making the change.

    Raises:
        ValueError: If the username is taken, or a USER role has no wa_id.
    """
    username = username.strip()
    if not username:
        raise ValueError("A username is required.")
    if await get_user_by_username(db, username):
        raise ValueError(f"The username '{username}' is already taken.")
    if len(password) < 8:
        raise ValueError("The password must be at least 8 characters.")
    if role is UserRole.USER and not wa_id:
        raise ValueError("A user account must be linked to a WhatsApp number.")

    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        display_name=(display_name or "").strip() or None,
        # Only the USER role is number-scoped; storing a wa_id on an admin
        # would be misleading.
        wa_id=wa_id.strip() if (wa_id and role is UserRole.USER) else None,
        created_by=created_by,
    )
    db.add(user)
    await db.flush()

    logger.info(
        f"Created {role.value} login '{username}'.",
        extra={"event": "user_created", "username": username, "role": role.value},
    )
    return user


async def update_user(
    db: AsyncSession,
    user: User,
    role: Optional[UserRole] = None,
    display_name: Optional[str] = None,
    wa_id: Optional[str] = None,
    is_active: Optional[bool] = None,
    password: Optional[str] = None,
) -> User:
    """Updates a login, refusing changes that would remove the last administrator."""
    if role is not None and role is not user.role_enum:
        if user.role_enum is UserRole.ADMIN and await count_admins(db, exclude_id=user.id) == 0:
            raise ValueError("This is the only administrator; change another account to admin first.")
        user.role = role
        # Dropping out of the USER role releases the number scope.
        if role is not UserRole.USER:
            user.wa_id = None

    if display_name is not None:
        user.display_name = display_name.strip() or None

    if wa_id is not None and user.role_enum is UserRole.USER:
        if not wa_id.strip():
            raise ValueError("A user account must stay linked to a WhatsApp number.")
        user.wa_id = wa_id.strip()

    if is_active is not None and is_active != user.is_active:
        if not is_active and user.role_enum is UserRole.ADMIN and await count_admins(db, exclude_id=user.id) == 0:
            raise ValueError("This is the only administrator; you cannot deactivate it.")
        user.is_active = is_active

    if password:
        if len(password) < 8:
            raise ValueError("The password must be at least 8 characters.")
        user.password_hash = hash_password(password)

    await db.flush()
    logger.info(
        f"Updated login '{user.username}'.",
        extra={"event": "user_updated", "username": user.username},
    )
    return user


async def delete_user(db: AsyncSession, user: User) -> None:
    """Deletes a login, refusing to remove the last administrator."""
    if user.role_enum is UserRole.ADMIN and await count_admins(db, exclude_id=user.id) == 0:
        raise ValueError("This is the only administrator; you cannot delete it.")
    await db.delete(user)
    await db.flush()
    logger.info(
        f"Deleted login '{user.username}'.",
        extra={"event": "user_deleted", "username": user.username},
    )


async def record_audit(
    db: AsyncSession,
    actor: str,
    action: str,
    target: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """Appends an entry to the audit trail."""
    db.add(AuditLog(actor=actor, action=action, target=target, detail=detail))
    await db.flush()


async def recent_audit(db: AsyncSession, limit: int = 20) -> List[AuditLog]:
    """Returns the most recent audit entries."""
    result = await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    return list(result.scalars().all())
