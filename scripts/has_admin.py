"""Exits 0 when at least one dashboard login exists, 1 otherwise.

Used by setup.bat and deploy/install.sh to decide whether to prompt for one.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


async def has_any_login() -> bool:
    """Returns True when the users table holds at least one row."""
    from sqlalchemy import func, select

    from app.db.base import init_database, session_scope
    from app.db.models import User

    await init_database()
    async with session_scope() as session:
        count = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        return bool(count)


if __name__ == "__main__":
    try:
        raise SystemExit(0 if asyncio.run(has_any_login()) else 1)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Could not check for existing logins: {exc}", file=sys.stderr)
        raise SystemExit(1)
