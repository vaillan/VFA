"""Pool de sesiones persistentes de navegador conectadas via CDP.

Las tools QA adquieren/liberan sesiones del pool para mantener viva la
conexion entre llamadas, identificadas por session_id via ContextVar.
"""

import asyncio
import contextlib
import contextvars
import time
from dataclasses import dataclass
from typing import Any, Iterator

from app import browser as _browser_mod
from app import config


@dataclass
class Session:
    """Sesion de navegador adquirida del pool."""

    session_id: str
    browser: Any
    page: Any
    last_used: float
    transient: bool = False


class SessionPool:
    """Mantiene sesiones de navegador reutilizables con TTL y eviccion LRU."""

    def __init__(self, ttl: float, max_size: int, enabled: bool = True) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._enabled = enabled
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, session_id: str) -> Session:
        """Obtiene una sesion reutilizable o crea una nueva."""
        if not self._enabled:
            async with self._lock:
                browser = await _browser_mod._connect_browser()
                page = await _browser_mod._new_page(browser)
                session = Session(
                    session_id=session_id,
                    browser=browser,
                    page=page,
                    last_used=time.monotonic(),
                    transient=True,
                )
                self._sessions[session_id] = session
                return session
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                if not _browser_mod._is_session_dead(session.browser, session.page):
                    session.last_used = time.monotonic()
                    return session
                await _browser_mod._close_browser(session.browser)
                del self._sessions[session_id]
            await self._evict_locked()
            browser = await _browser_mod._connect_browser()
            page = await _browser_mod._new_page(browser)
            session = Session(
                session_id=session_id,
                browser=browser,
                page=page,
                last_used=time.monotonic(),
            )
            self._sessions[session_id] = session
            return session

    async def release(self, session_id: str) -> None:
        """Libera la sesion; las transitorias se cierran y las persistentes se conservan."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            if session.transient:
                await _browser_mod._close_browser(session.browser)
                del self._sessions[session_id]
            else:
                session.last_used = time.monotonic()

    async def _evict_locked(self) -> None:
        """Elimina sesiones expiradas por TTL y las sobrantes por LRU (lock tomado)."""
        now = time.monotonic()
        expired = [
            sid
            for sid, session in self._sessions.items()
            if now - session.last_used > self._ttl
        ]
        for sid in expired:
            await _browser_mod._close_browser(self._sessions[sid].browser)
            del self._sessions[sid]
        while len(self._sessions) >= self._max_size:
            sid = min(self._sessions, key=lambda s: self._sessions[s].last_used)
            await _browser_mod._close_browser(self._sessions[sid].browser)
            del self._sessions[sid]

    async def close(self, session_id: str) -> None:
        """Cierra y elimina la sesion indicada."""
        async with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is not None:
                await _browser_mod._close_browser(session.browser)

    async def cleanup(self) -> None:
        """Cierra todas las sesiones expiradas por TTL."""
        async with self._lock:
            await self._evict_locked()

    async def close_all(self) -> None:
        """Cierra todos los navegadores y vacia el pool."""
        async with self._lock:
            for session in self._sessions.values():
                await _browser_mod._close_browser(session.browser)
            self._sessions.clear()


_current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "vfa_session", default="default"
)


def get_current_session_id() -> str:
    """Devuelve el session_id activo en el contexto actual."""
    return _current_session_id.get()


def set_current_session_id(session_id: str) -> contextvars.Token:
    """Fija el session_id actual y devuelve el token para restaurarlo."""
    return _current_session_id.set(session_id)


def reset_current_session_id(token: contextvars.Token) -> None:
    """Restaura el session_id previo usando el token de set_current_session_id."""
    _current_session_id.reset(token)


@contextlib.contextmanager
def session_context(session_id: str) -> Iterator[None]:
    """Contexto que fija el session_id y lo restaura al salir."""
    token = set_current_session_id(session_id)
    try:
        yield
    finally:
        reset_current_session_id(token)


pool = SessionPool(
    ttl=config.get_session_pool_ttl(),
    max_size=config.get_session_pool_max_size(),
    enabled=config.get_session_pool_enabled(),
)