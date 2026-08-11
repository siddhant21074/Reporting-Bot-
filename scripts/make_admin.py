"""Creates the first dashboard administrator, or prints values for .env.

Normal use -- create the login directly in the database:

    python scripts/make_admin.py --create
    python scripts/make_admin.py --create --username akash

Non-interactive, or if your terminal will not accept a hidden password:

    python scripts/make_admin.py --create --password "your password"
    python scripts/make_admin.py --create --random

Before the database exists, or to seed SECRET_KEY into .env:

    python scripts/make_admin.py
"""

import argparse
import asyncio
import os
import secrets
import string
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

MIN_LENGTH = 8
RECOMMENDED_LENGTH = 12


def _hidden_input_works() -> bool:
    """Whether this terminal can read a password without echoing it.

    On Windows, ``getpass`` uses ``msvcrt.getwch()``, which only works in a real
    console. Git Bash and other MSYS/MinTTY terminals are pipes rather than
    consoles, so that call blocks forever and it looks as though typing does
    nothing. Detect it and use a visible prompt instead of hanging.
    """
    if not sys.stdin.isatty():
        return False

    # MSYSTEM is set by Git Bash / MSYS2; MinTTY sets an xterm-ish TERM.
    # Only stdin matters here: win_getpass reads the console directly and
    # writes its prompt with msvcrt, so a redirected stdout is fine -- and
    # falling back to visible input in that case would write the password
    # into whatever file the output was redirected to.
    if os.name == "nt":
        if os.environ.get("MSYSTEM") or os.environ.get("TERM", "").startswith("xterm"):
            return False

    return True


def _read_twice(reader, label: str) -> str:
    """Reads a password twice through ``reader`` and checks the two match."""
    first = reader(f"{label}: ")
    second = reader("Confirm password: ")
    if first != second:
        raise ValueError("The passwords did not match. Nothing was changed.")
    return first


def generate_password(length: int = 16) -> str:
    """Generates a readable random password.

    Excludes characters that are easy to misread when someone copies the
    password out of a terminal by hand.
    """
    alphabet = (
        string.ascii_lowercase.replace("l", "").replace("o", "")
        + string.ascii_uppercase.replace("I", "").replace("O", "")
        + string.digits.replace("0", "").replace("1", "")
        + "!@#$%^&*-_=+"
    )
    return "".join(secrets.choice(alphabet) for _ in range(length))


def obtain_password(supplied: str, use_random: bool) -> str:
    """Returns the password to use, prompting only when necessary.

    Raises:
        ValueError: If no password could be obtained, with advice on what to do.
    """
    if supplied:
        return supplied

    if use_random:
        password = generate_password()
        print("\n  Generated password:\n")
        print(f"      {password}\n")
        print("  Copy it now -- it is not stored anywhere and cannot be shown again.\n")
        return password

    if _hidden_input_works():
        import getpass

        print("\n  Choose a password for the dashboard administrator.")
        print("  Your typing is hidden -- no characters or dots will appear.\n")
        return _read_twice(getpass.getpass, "New password")

    if not sys.stdin.isatty():
        raise ValueError(
            "There is no terminal to read a password from.\n"
            "  Pass one instead:\n"
            '      python scripts/make_admin.py --create --password "your password"\n'
            "  Or have one generated:\n"
            "      python scripts/make_admin.py --create --random"
        )

    # A terminal that cannot hide input -- Git Bash and similar. Reading
    # visibly is better than hanging on a prompt that never accepts a key.
    print("\n  This terminal cannot hide password input, so what you type will be visible.")
    print("  For a hidden prompt, run the same command from Command Prompt or PowerShell.")
    print("  Alternatives:  --password \"your password\"   or   --random\n")

    try:
        return _read_twice(lambda prompt: input(prompt), "New password (visible)")
    except EOFError:
        raise ValueError(
            "No input was received.\n"
            '  Pass the password directly:  --password "your password"'
        )


async def create_login(username: str, password: str, display_name: str) -> int:
    """Creates an administrator in the database."""
    from app.db.base import init_database, session_scope
    from app.db.models import UserRole
    from app.repositories import users as users_repo

    await init_database()

    async with session_scope() as session:
        existing = await users_repo.get_user_by_username(session, username)
        if existing:
            print(f"\n  A login called '{username}' already exists.", file=sys.stderr)
            print("  Choose a different username, or manage it from the portal.", file=sys.stderr)
            return 1

        await users_repo.create_user(
            session,
            username=username,
            password=password,
            role=UserRole.ADMIN,
            display_name=display_name or None,
            created_by="setup",
        )
        await session.commit()

    print(f"\n  Administrator '{username}' created.")
    print("  Sign in at http://localhost:8000/login\n")
    return 0


def print_env_values(username: str, password: str) -> int:
    """Prints values to paste into .env, for the pre-database case."""
    from app.core.security import hash_password

    print("\nAdd these to your .env:\n")
    print(f'ADMIN_USERNAME="{username}"')
    print(f'ADMIN_PASSWORD_HASH="{hash_password(password)}"')
    print(f'SECRET_KEY="{secrets.token_urlsafe(48)}"')
    print("\nSECRET_KEY signs the dashboard session cookie and is required in production.")
    print("Then run with --create to add the login to the database.\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the first dashboard administrator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python scripts/make_admin.py --create\n"
            '  python scripts/make_admin.py --create --username akash --password "s3cret pass"\n'
            "  python scripts/make_admin.py --create --random\n"
        ),
    )
    parser.add_argument("--create", action="store_true", help="Create the login in the database.")
    parser.add_argument("--username", default="admin", help="Username (default: admin).")
    parser.add_argument("--name", default="", help="Full name, shown in the portal sidebar.")
    parser.add_argument("--password", default="", help="Password. Prompted for if omitted.")
    parser.add_argument(
        "--random", action="store_true", help="Generate a strong password and print it."
    )
    args = parser.parse_args()

    try:
        password = obtain_password(args.password, args.random)
    except ValueError as exc:
        print(f"\n  {exc}\n", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n  Cancelled. Nothing was changed.\n", file=sys.stderr)
        return 1

    if len(password) < MIN_LENGTH:
        print(f"\n  The password must be at least {MIN_LENGTH} characters.\n", file=sys.stderr)
        return 1
    if len(password) < RECOMMENDED_LENGTH:
        print(
            f"  Note: {RECOMMENDED_LENGTH} characters or more is safer for a portal "
            "reachable from the internet.",
            file=sys.stderr,
        )

    try:
        if args.create:
            return asyncio.run(create_login(args.username, password, args.name))
        return print_env_values(args.username, password)
    except Exception as exc:
        print(f"\n  Failed: {exc}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
