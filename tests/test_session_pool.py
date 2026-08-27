"""Tests unitarios del pool de sesiones persistentes del navegador."""

import asyncio
from typing import Any

import pytest

from app import browser as browser_mod
from app import session_pool as sp


class FakeBrowser:
    """Navegador fake con ciclo de vida controlable."""

    def __init__(self, dead: bool = False) -> None:
        self._dead = dead
        self.closed = False

    def is_connected(self) -> bool:
        return not self._dead and not self.closed

    async def close(self) -> None:
        self.closed = True


class FakePage:
    """Pagina fake minima para las sesiones del pool."""

    def is_closed(self) -> bool:
        return False


def install_browser_fakes(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[FakeBrowser], list[FakeBrowser]]:
    """Reemplaza los helpers de navegador por fakes y devuelve (creadas, cerradas)."""

    creadas: list[FakeBrowser] = []
    cerradas: list[FakeBrowser] = []

    async def fake_connect() -> FakeBrowser:
        browser = FakeBrowser()
        creadas.append(browser)
        return browser

    async def fake_new_page(browser: Any) -> FakePage:
        return FakePage()

    async def fake_close_browser(browser: Any) -> None:
        cerradas.append(browser)
        await browser.close()

    def fake_is_session_dead(browser: Any, page: Any) -> bool:
        return not browser.is_connected() or page.is_closed()

    monkeypatch.setattr(browser_mod, "_connect_browser", fake_connect)
    monkeypatch.setattr(browser_mod, "_new_page", fake_new_page)
    monkeypatch.setattr(browser_mod, "_close_browser", fake_close_browser)
    monkeypatch.setattr(browser_mod, "_is_session_dead", fake_is_session_dead)
    return creadas, cerradas


@pytest.mark.asyncio
async def test_acquire_crea_y_reutiliza(monkeypatch: pytest.MonkeyPatch) -> None:
    creadas, _ = install_browser_fakes(monkeypatch)
    pool = sp.SessionPool(ttl=60.0, max_size=5)

    first = await pool.acquire("s1")
    second = await pool.acquire("s1")

    assert first is second
    assert len(creadas) == 1


@pytest.mark.asyncio
async def test_acquire_recrea_si_muerta(monkeypatch: pytest.MonkeyPatch) -> None:
    creadas, cerradas = install_browser_fakes(monkeypatch)
    pool = sp.SessionPool(ttl=60.0, max_size=5)

    first = await pool.acquire("s1")
    first.browser._dead = True  # type: ignore[attr-defined]

    second = await pool.acquire("s1")

    assert first is not second
    assert creadas == [first.browser, second.browser]
    assert cerradas == [first.browser]


@pytest.mark.asyncio
async def test_release_no_cierra_sesion_persistente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creadas, cerradas = install_browser_fakes(monkeypatch)
    pool = sp.SessionPool(ttl=60.0, max_size=5)

    session = await pool.acquire("s1")
    await pool.release("s1")

    assert session.browser.closed is False
    assert cerradas == []
    assert pool._sessions["s1"] is session


@pytest.mark.asyncio
async def test_evition_por_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    _, cerradas = install_browser_fakes(monkeypatch)
    pool = sp.SessionPool(ttl=0.0, max_size=5)

    session = await pool.acquire("s1")
    await asyncio.sleep(0.01)
    await pool.cleanup()

    assert "s1" not in pool._sessions
    assert cerradas == [session.browser]


@pytest.mark.asyncio
async def test_eviction_lru_por_max_size(monkeypatch: pytest.MonkeyPatch) -> None:
    _, cerradas = install_browser_fakes(monkeypatch)
    pool = sp.SessionPool(ttl=60.0, max_size=2)

    s1 = await pool.acquire("s1")
    await asyncio.sleep(0.01)
    s2 = await pool.acquire("s2")
    await asyncio.sleep(0.01)
    s3 = await pool.acquire("s3")

    assert "s1" not in pool._sessions
    assert "s2" in pool._sessions
    assert "s3" in pool._sessions
    assert cerradas == [s1.browser]


@pytest.mark.asyncio
async def test_modo_transitorio(monkeypatch: pytest.MonkeyPatch) -> None:
    creadas, cerradas = install_browser_fakes(monkeypatch)
    pool = sp.SessionPool(ttl=60.0, max_size=5, enabled=False)

    session = await pool.acquire("s1")

    assert session.transient is True
    assert "s1" in pool._sessions
    assert len(creadas) == 1

    await pool.release("s1")

    assert session.browser.closed is True
    assert "s1" not in pool._sessions
    assert cerradas == [session.browser]


@pytest.mark.asyncio
async def test_close_all_cierra_todo(monkeypatch: pytest.MonkeyPatch) -> None:
    _, cerradas = install_browser_fakes(monkeypatch)
    pool = sp.SessionPool(ttl=60.0, max_size=5)

    s1 = await pool.acquire("s1")
    s2 = await pool.acquire("s2")
    await pool.close_all()

    assert s1.browser.closed is True
    assert s2.browser.closed is True
    assert len(cerradas) == 2


@pytest.mark.asyncio
async def test_contextvar_helpers() -> None:
    token = sp.set_current_session_id("test-123")
    assert sp.get_current_session_id() == "test-123"
    sp.reset_current_session_id(token)
    assert sp.get_current_session_id() == "default"


@pytest.mark.asyncio
async def test_session_context_manager() -> None:
    with sp.session_context("ctx-1"):
        assert sp.get_current_session_id() == "ctx-1"
    assert sp.get_current_session_id() == "default"