"""Session management: stores per-session PropertyAgent instances with TTL."""

import time
from collections import OrderedDict
from agent import PropertyAgent


class SessionStore:
    """Manages PropertyAgent instances per session with LRU eviction and TTL.

    Each session (browser) gets its own agent instance with isolated conversation history.
    Expired sessions are evicted to prevent unbounded memory growth.
    """

    def __init__(self, max_sessions: int = 500, ttl_seconds: int = 1800):
        """Initialize the session store.

        Args:
            max_sessions: Maximum number of concurrent sessions to keep in memory
            ttl_seconds: Session expiry time in seconds (30 minutes default)
        """
        self._sessions: OrderedDict[str, dict] = OrderedDict()
        self._max_sessions = max_sessions
        self._ttl_seconds = ttl_seconds

    def get_or_create(self, session_id: str, kb_url: str, openai_api_key: str) -> PropertyAgent:
        """Get an existing session's agent or create a new one.

        Args:
            session_id: Unique session identifier (UUID)
            kb_url: KB-Pipeline service URL
            openai_api_key: OpenAI API key

        Returns:
            PropertyAgent instance for this session
        """
        now = time.time()

        # Return existing session if not expired
        if session_id in self._sessions:
            session_data = self._sessions[session_id]
            if now - session_data["last_seen"] < self._ttl_seconds:
                session_data["last_seen"] = now
                # Move to end (most recently used)
                self._sessions.move_to_end(session_id)
                return session_data["agent"]
            else:
                # Session expired, remove it
                del self._sessions[session_id]

        # Evict old sessions if at capacity
        self._evict_expired()
        if len(self._sessions) >= self._max_sessions:
            # Remove least recently used
            lru_key = next(iter(self._sessions))
            del self._sessions[lru_key]

        # Create new session
        agent = PropertyAgent(kb_url=kb_url, openai_api_key=openai_api_key)
        self._sessions[session_id] = {
            "agent": agent,
            "created_at": now,
            "last_seen": now,
        }
        return agent

    def reset(self, session_id: str) -> None:
        """Reset (clear history) for a specific session.

        Args:
            session_id: Session to reset
        """
        if session_id in self._sessions:
            self._sessions[session_id]["agent"].reset()
            self._sessions[session_id]["last_seen"] = time.time()

    def _evict_expired(self) -> None:
        """Remove all expired sessions."""
        now = time.time()
        expired = [
            sid
            for sid, data in self._sessions.items()
            if now - data["last_seen"] >= self._ttl_seconds
        ]
        for sid in expired:
            del self._sessions[sid]
