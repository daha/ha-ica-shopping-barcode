"""Exceptions raised by the ICA API client."""

from __future__ import annotations


class IcaError(Exception):
    """Base error for all ICA client failures."""


class IcaAuthError(IcaError):
    """Authentication failed (bad credentials or unrecoverable token error)."""


class IcaConnectionError(IcaError):
    """Network or transport error talking to ICA."""


class IcaGatewayBlockedError(IcaConnectionError):
    """ICA's API gateway rejected the request (likely a non-Swedish IP)."""
