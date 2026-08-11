"""ICA authentication: OAuth2 + dynamic client registration + PKCE + login.

Ported from kanylbullen/ica-mcp (MIT) and LazyTarget/ha-ica-todo (MIT).
This module MUST NOT import from `homeassistant`.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp

from .const import (
    ACR,
    AUTHORIZE_ENDPOINT,
    DCR_CLIENT_ID,
    DCR_CLIENT_SECRET,
    DCR_SOFTWARE_ID,
    LOGIN_ENDPOINT,
    REDIRECT_URI,
    REGISTER_ENDPOINT,
    TOKEN_ENDPOINT,
    USER_AGENT,
)
from .exceptions import IcaAuthError, IcaConnectionError

_EXPIRY_MARGIN = timedelta(seconds=60)
_TOKEN_RE = re.compile(r'name="token"[^>]*value="([^"]+)"')


@dataclass
class IcaToken:
    """A cached ICA token bundle plus the dynamic client credentials."""

    access_token: str
    refresh_token: str
    expires_at: datetime
    client_id: str
    client_secret: str
    scope: str

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) >= (self.expires_at - _EXPIRY_MARGIN)

    def to_dict(self) -> dict[str, str]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> IcaToken:
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.fromisoformat(data["expires_at"]),
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            scope=data["scope"],
        )


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    verifier = re.sub(r"[^a-zA-Z0-9]", "", verifier)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _query_value(location: str, key: str) -> str:
    parsed = urlparse(location)
    values = parse_qs(parsed.query).get(key)
    if not values:
        raise IcaAuthError(f"Missing '{key}' in redirect: {location}")
    return values[0]


async def _raise_on_error_status(resp: aiohttp.ClientResponse) -> None:
    """Map a non-2xx/3xx response onto our exception hierarchy.

    400/401/403 mean bad credentials or a rejected grant (e.g. ``invalid_grant``
    on refresh) -> IcaAuthError. Anything else (5xx, unexpected 4xx) is treated
    as a transport/server problem -> IcaConnectionError. A short body snippet is
    included so the underlying OAuth error (if any) is visible in logs.
    """
    if resp.status < 400:
        return
    body = (await resp.text()).strip().replace("\n", " ")
    snippet = body[:200]
    message = f"HTTP {resp.status} from {resp.url}: {snippet}"
    if resp.status in (400, 401, 403):
        raise IcaAuthError(message)
    raise IcaConnectionError(message)


class IcaAuth:
    """Performs and refreshes ICA authentication over one aiohttp session."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: IcaToken | None = None,
        token_updated: Callable[[IcaToken], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._token = token
        self._token_updated = token_updated
        self._refresh_lock = asyncio.Lock()

    @property
    def token(self) -> IcaToken | None:
        return self._token

    def invalidate_token(self) -> None:
        """Force the next access-token request to refresh (marks it expired)."""
        if self._token is not None:
            self._token.expires_at = datetime.now(UTC)

    async def async_get_access_token(self) -> str:
        if self._token is None:
            raise IcaAuthError("Not authenticated; call login() first")
        if self._token.is_expired:
            async with self._refresh_lock:
                # Re-check inside the lock: a concurrent caller may have
                # already refreshed while we were waiting for it.
                if self._token.is_expired:
                    await self._refresh()
        return self._token.access_token

    async def login(self, personnummer: str, password: str) -> IcaToken:
        try:
            # Step 1: bootstrap client-credentials token (scope=dcr).
            bootstrap = await self._post_form(
                TOKEN_ENDPOINT,
                {
                    "client_id": DCR_CLIENT_ID,
                    "client_secret": DCR_CLIENT_SECRET,
                    "grant_type": "client_credentials",
                    "scope": "dcr",
                    "response_type": "token",
                },
            )
            # Step 2: dynamic client registration.
            reg = await self._post_json(
                REGISTER_ENDPOINT,
                {"software_id": DCR_SOFTWARE_ID},
                headers={"Authorization": f"Bearer {bootstrap['access_token']}"},
            )
            client_id = reg["client_id"]
            client_secret = reg["client_secret"]
            scope = reg["scope"]

            # Step 3: authorize (PKCE) -> capture state from redirect.
            verifier, challenge = _pkce_pair()
            state = await self._authorize_get(client_id, scope, challenge)

            # Step 4: post credentials -> extract SSO token from HTML form.
            sso_token = await self._login_form(personnummer, password)

            # Step 5: authorize with SSO token + state -> capture code.
            code = await self._authorize_post(client_id, sso_token, state)

            # Step 6: exchange code for access/refresh tokens.
            tok = await self._post_form(
                TOKEN_ENDPOINT,
                {
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "authorization_code",
                    "scope": scope,
                    "response_type": "token",
                    "code_verifier": verifier,
                    "redirect_uri": REDIRECT_URI,
                },
            )
        except aiohttp.ClientError as err:
            raise IcaConnectionError(str(err)) from err

        token = IcaToken(
            access_token=tok["access_token"],
            refresh_token=tok["refresh_token"],
            expires_at=datetime.now(UTC) + timedelta(seconds=int(tok["expires_in"])),
            client_id=client_id,
            client_secret=client_secret,
            scope=scope,
        )
        self._token = token
        await self._notify(token)
        return token

    async def _refresh(self) -> None:
        assert self._token is not None
        basic = base64.b64encode(
            f"{self._token.client_id}:{self._token.client_secret}".encode()
        ).decode()
        try:
            data = await self._post_form(
                TOKEN_ENDPOINT,
                {
                    "grant_type": "refresh_token",
                    "refresh_token": self._token.refresh_token,
                },
                headers={"Authorization": f"Basic {basic}"},
            )
        except aiohttp.ClientError as err:
            raise IcaConnectionError(str(err)) from err
        self._token = IcaToken(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", self._token.refresh_token),
            expires_at=datetime.now(UTC) + timedelta(seconds=int(data["expires_in"])),
            client_id=self._token.client_id,
            client_secret=self._token.client_secret,
            scope=data.get("scope", self._token.scope),
        )
        await self._notify(self._token)

    async def _notify(self, token: IcaToken) -> None:
        if self._token_updated is not None:
            await self._token_updated(token)

    async def _authorize_get(self, client_id: str, scope: str, challenge: str) -> str:
        params = {
            "client_id": client_id,
            "scope": scope,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "login",
            "acr": ACR,
        }
        async with self._session.get(
            AUTHORIZE_ENDPOINT,
            params=params,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=False,
        ) as resp:
            await _raise_on_error_status(resp)
            location = resp.headers.get("Location", "")
        state = _query_value(location, "state")

        # Follow the redirect (loads the Curity login page and establishes its
        # session cookie on `self._session`) before posting credentials, matching
        # upstream (kanylbullen/ica-mcp client.py `_full_login`):
        #   state = self._qs(r.headers["Location"], "state")
        #   self.session.get(r.headers["Location"], timeout=30).raise_for_status()
        async with self._session.get(
            location,
            headers={"User-Agent": USER_AGENT},
        ) as redirect_resp:
            await _raise_on_error_status(redirect_resp)

        return state

    async def _login_form(self, personnummer: str, password: str) -> str:
        async with self._session.post(
            LOGIN_ENDPOINT,
            data={"userName": personnummer, "password": password},
            headers={"User-Agent": USER_AGENT},
        ) as resp:
            html = await resp.text()
            if resp.status in (400, 401, 403):
                raise IcaAuthError("Invalid personnummer or password")
            if resp.status >= 400:
                raise IcaConnectionError(f"Login request failed: HTTP {resp.status}")
        match = _TOKEN_RE.search(html)
        if not match:
            raise IcaAuthError("Login failed: no SSO token in response")
        return match.group(1)

    async def _authorize_post(self, client_id: str, sso_token: str, state: str) -> str:
        async with self._session.post(
            AUTHORIZE_ENDPOINT,
            params={"client_id": client_id, "forceAuthN": "true", "acr": ACR},
            data={"token": sso_token, "state": state},
            headers={"User-Agent": USER_AGENT},
            allow_redirects=False,
        ) as resp:
            await _raise_on_error_status(resp)
            location = resp.headers.get("Location", "")
        return _query_value(location, "code")

    async def _post_form(
        self,
        url: str,
        data: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        merged = {"User-Agent": USER_AGENT, **(headers or {})}
        async with self._session.post(url, data=data, headers=merged) as resp:
            await _raise_on_error_status(resp)
            payload: dict[str, Any] = await resp.json()
            return payload

    async def _post_json(
        self,
        url: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        merged = {"User-Agent": USER_AGENT, **(headers or {})}
        async with self._session.post(url, json=data, headers=merged) as resp:
            await _raise_on_error_status(resp)
            payload: dict[str, Any] = await resp.json()
            return payload
