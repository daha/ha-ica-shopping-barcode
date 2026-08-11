"""Tests for the ICA authentication flow (mocked HTTP)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import aiohttp
import pytest
from aioresponses import aioresponses
from custom_components.ica.api import const as c
from custom_components.ica.api.auth import IcaAuth, IcaToken
from custom_components.ica.api.exceptions import IcaAuthError, IcaConnectionError

# `_authorize_get`/`_authorize_post` attach query params via `params=`, so
# aioresponses' exact-URL matching needs a pattern rather than the bare endpoint.
_AUTHORIZE_URL_RE = re.compile(rf"^{re.escape(c.AUTHORIZE_ENDPOINT)}(\?.*)?$")


def _future() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


def _past() -> datetime:
    return datetime.now(UTC) - timedelta(hours=1)


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


async def test_refresh_error_body_raises_ica_auth_error() -> None:
    """A 400 invalid_grant body must map to IcaAuthError, not a bare KeyError."""
    stale = IcaToken("old", "bad-refresh", _past(), "cid", "sec", "scope")
    async with aiohttp.ClientSession() as session:
        auth = IcaAuth(session, token=stale)
        with aioresponses() as mock:
            mock.post(
                c.TOKEN_ENDPOINT,
                status=400,
                payload={"error": "invalid_grant"},
            )
            with pytest.raises(IcaAuthError):
                await auth.async_get_access_token()


async def test_login_full_flow() -> None:
    """Drive IcaAuth.login() end-to-end with every HTTP step mocked.

    Sequence mirrors upstream kanylbullen/ica-mcp `_full_login`: bootstrap ->
    DCR register -> authorize GET (redirect carrying `state`) -> GET the
    redirect Location (loads the login page / establishes the session cookie,
    Fix 2) -> POST credentials (HTML with a hidden SSO `token` field) ->
    authorize POST with the SSO token (redirect carrying `code`) -> exchange
    the code for the final access/refresh tokens.
    """
    updated: list[IcaToken] = []

    async def on_update(tok: IcaToken) -> None:
        updated.append(tok)

    login_page_location = f"{c.IMS_BASE}/authn/methods/html-form?state=abc123"
    code_redirect_location = f"{c.REDIRECT_URI}?code=auth-code-xyz&state=abc123"

    async with aiohttp.ClientSession() as session:
        auth = IcaAuth(session, token_updated=on_update)
        with aioresponses() as mock:
            # Step 1: bootstrap client-credentials token (scope=dcr).
            mock.post(
                c.TOKEN_ENDPOINT,
                payload={"access_token": "bootstrap-tok", "expires_in": 900},
            )
            # Step 2: dynamic client registration.
            mock.post(
                c.REGISTER_ENDPOINT,
                payload={
                    "client_id": "dyn-client-id",
                    "client_secret": "dyn-client-secret",
                    "scope": "myscope",
                },
            )
            # Step 3: authorize GET -> 302 redirect carrying `state`.
            mock.get(
                _AUTHORIZE_URL_RE,
                status=302,
                headers={"Location": login_page_location},
            )
            # Step 3b (Fix 2): follow that redirect before posting credentials.
            mock.get(login_page_location, status=200, body="<html>login page</html>")
            # Step 4: post credentials -> HTML with a hidden SSO token field.
            mock.post(
                c.LOGIN_ENDPOINT,
                status=200,
                body='<html><input name="token" value="sso-token-xyz"/></html>',
            )
            # Step 5: authorize POST with SSO token + state -> 302 with `code`.
            mock.post(
                _AUTHORIZE_URL_RE,
                status=302,
                headers={"Location": code_redirect_location},
            )
            # Step 6: exchange code for the final access/refresh tokens.
            mock.post(
                c.TOKEN_ENDPOINT,
                payload={
                    "access_token": "final-access",
                    "refresh_token": "final-refresh",
                    "expires_in": 900,
                },
            )

            token = await auth.login("197801011234", "s3cret")

    assert token.access_token == "final-access"
    assert token.refresh_token == "final-refresh"
    assert token.client_id == "dyn-client-id"
    assert token.client_secret == "dyn-client-secret"
    assert token.scope == "myscope"
    assert auth.token is token
    assert updated and updated[-1].access_token == "final-access"


async def test_login_form_server_error_raises_connection_error() -> None:
    async with aiohttp.ClientSession() as session:
        auth = IcaAuth(session)
        with aioresponses() as mock:
            mock.post(c.LOGIN_ENDPOINT, status=503, body="upstream down")
            with pytest.raises(IcaConnectionError):
                await auth._login_form("199001010000", "secret")


async def test_login_form_bad_credentials_raises_auth_error() -> None:
    async with aiohttp.ClientSession() as session:
        auth = IcaAuth(session)
        with aioresponses() as mock:
            mock.post(c.LOGIN_ENDPOINT, status=401, body="nope")
            with pytest.raises(IcaAuthError):
                await auth._login_form("199001010000", "wrong")
