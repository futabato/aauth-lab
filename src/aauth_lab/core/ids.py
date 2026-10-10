"""Identifier types (§11.1, §5.2) and scopes (§11.10)."""

import re
import secrets
from typing import NewType
from urllib.parse import urlsplit

ServerId = NewType("ServerId", str)
"""An issuer URL: scheme and host only, compared by exact string match (§11.1.1)."""

AgentId = NewType("AgentId", str)
"""``aauth:local@domain`` (§5.2)."""

Jti = NewType("Jti", str)
Sub = NewType("Sub", str)
MissionS256 = NewType("MissionS256", str)

_AGENT_ID = re.compile(r"^aauth:([A-Za-z0-9._+-]{1,255})@([a-z0-9.-]+)$")


class IdentifierError(ValueError):
    pass


def server_id(value: str, *, allow_loopback_http: bool) -> ServerId:
    """Validate a server identifier.

    The spec requires ``https`` with no port (§11.1.1). A lab running every role on
    one machine cannot satisfy that, so ``allow_loopback_http`` admits
    ``http://localhost:<port>`` / ``http://127.0.0.1:<port>`` and nothing else.
    """
    parts = urlsplit(value)
    if value != value.lower() or value.endswith("/"):
        raise IdentifierError(f"not a server identifier: {value!r}")
    if parts.path or parts.query or parts.fragment or parts.username:
        raise IdentifierError(f"server identifier has path/query/fragment: {value!r}")
    if parts.scheme == "https" and parts.port is None and parts.hostname:
        return ServerId(value)
    if (
        allow_loopback_http
        and parts.scheme == "http"
        and parts.hostname in ("localhost", "127.0.0.1")
    ):
        return ServerId(value)
    raise IdentifierError(f"server identifier must be https without port: {value!r}")


def agent_id(value: str) -> AgentId:
    match = _AGENT_ID.match(value)
    if match is None:
        raise IdentifierError(f"not an agent identifier: {value!r}")
    return AgentId(value)


def new_jti(prefix: str) -> Jti:
    return Jti(f"{prefix}-{secrets.token_urlsafe(9)}")


Scope = frozenset[str]


def parse_scope(value: str | None) -> Scope:
    return frozenset(value.split()) if value else frozenset()


def format_scope(scope: Scope) -> str:
    return " ".join(sorted(scope))
