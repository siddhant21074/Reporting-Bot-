"""In-memory session store with per-sender serialisation.

Two webhooks from the same person can arrive at once -- sending three photos in
a row reliably does it. The store therefore hands out a per-sender lock that the
caller holds for the whole read-modify-write cycle, so concurrent messages queue
behind each other instead of interleaving and losing state.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, List

from app.sessions.models import UserSession

logger = logging.getLogger("app.sessions.store")


class SessionStore:
    """Async in-memory store for active user sessions."""

    def __init__(self, timeout_seconds: int = 1800):
        """Initializes the store.

        Args:
            timeout_seconds: Idle time after which a session is considered expired.
        """
        self.timeout_seconds = timeout_seconds
        self._sessions: Dict[str, UserSession] = {}
        self._sender_locks: Dict[str, asyncio.Lock] = {}
        self._lock = asyncio.Lock()

    async def _get_sender_lock(self, sender_id: str) -> asyncio.Lock:
        """Returns the lock guarding one sender's session."""
        async with self._lock:
            lock = self._sender_locks.get(sender_id)
            if lock is None:
                lock = asyncio.Lock()
                self._sender_locks[sender_id] = lock
            return lock

    @asynccontextmanager
    async def transaction(self, sender_id: str) -> AsyncIterator[UserSession]:
        """Yields a sender's session with exclusive access, saving it on exit.

        Args:
            sender_id: The wa_id or chat id owning the session.

        Yields:
            The live ``UserSession``. Mutations are persisted when the block
            exits, including on error, so partial progress is not lost.
        """
        lock = await self._get_sender_lock(sender_id)
        async with lock:
            session = await self.get_session(sender_id)
            try:
                yield session
            finally:
                await self.save_session(session)

    async def get_session(self, sender_id: str) -> UserSession:
        """Returns the active session for a sender, replacing it if expired."""
        async with self._lock:
            session = self._sessions.get(sender_id)
            if session and session.is_expired(self.timeout_seconds):
                logger.info(
                    f"Session for '{sender_id}' expired; starting a fresh one.",
                    extra={"event": "session_expired", "sender": sender_id},
                )
                session = None

            if session is None:
                session = UserSession(sender_id=sender_id)
                self._sessions[sender_id] = session

            return session

    async def save_session(self, session: UserSession) -> None:
        """Persists a session and refreshes its activity timestamp."""
        async with self._lock:
            session.touch()
            self._sessions[session.sender_id] = session

    async def reset_session(self, sender_id: str) -> UserSession:
        """Replaces a sender's session with a fresh IDLE one."""
        async with self._lock:
            session = UserSession(sender_id=sender_id)
            self._sessions[sender_id] = session
            logger.info(
                f"Reset session for '{sender_id}'.",
                extra={"event": "session_reset", "sender": sender_id},
            )
            return session

    async def active_sessions(self) -> List[UserSession]:
        """Returns every non-expired session, for the dashboard."""
        async with self._lock:
            return [s for s in self._sessions.values() if not s.is_expired(self.timeout_seconds)]

    async def clear_expired_sessions(self) -> int:
        """Purges expired sessions and their locks.

        Returns:
            The number of sessions removed.
        """
        async with self._lock:
            expired = [
                sender_id for sender_id, session in self._sessions.items()
                if session.is_expired(self.timeout_seconds)
            ]
            for sender_id in expired:
                del self._sessions[sender_id]
                # Only drop the lock if nobody is waiting on it.
                lock = self._sender_locks.get(sender_id)
                if lock is not None and not lock.locked():
                    self._sender_locks.pop(sender_id, None)
            return len(expired)
