"""Tests for the ICA authentication flow (mocked HTTP)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.ica.api import const as c
from custom_components.ica.api.auth import IcaAuth, IcaToken


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=1)


def _past() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=1)


def test_token_is_expired() -> None:
    fresh = IcaToken("a", "r", _future(), "cid", "sec", "scope")
    stale = IcaToken("a", "r", _past(), "cid", "sec", "scope")
    assert fresh.is_expired is False
    assert stale.is_expired is True


def test_token_roundtrip() -> None:
    token = IcaToken("a", "r", _future(), "cid", "sec", "scope")
    assert IcaToken.from_dict(token.to_dict()) == token


async def test_async_get_access_token_refreshes_when_expired() -> None:
    updated: list[IcaToken] = []

    async def on_update(tok: IcaToken) -> None:
        updated.append(tok)

    stale = IcaToken("old", "refresh-me", _past(), "cid", "sec", "scope")
    async with aiohttp.ClientSession() as session:
        auth = IcaAuth(session, token=stale, token_updated=on_update)
        with aioresponses() as mock:
            mock.post(
                c.TOKEN_ENDPOINT,
                payload={
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 900,
                },
            )
            access = await auth.async_get_access_token()

    assert access == "new-access"
    assert auth.token is not None
    assert auth.token.refresh_token == "new-refresh"
    assert updated and updated[-1].access_token == "new-access"


async def test_async_get_access_token_returns_cached_when_fresh() -> None:
    fresh = IcaToken("cached", "r", _future(), "cid", "sec", "scope")
    async with aiohttp.ClientSession() as session:
        auth = IcaAuth(session, token=fresh)
        access = await auth.async_get_access_token()
    assert access == "cached"
