"""Metadata and JWKS discovery: ``{iss}/.well-known/{dwk}`` → ``jwks_uri`` (§11.2, §11.4)."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import httpx

from aauth_lab.core.encoding import JsonObject, parse_json_object
from aauth_lab.core.ids import ServerId
from aauth_lab.core.keys import Jwk, Jwks
from aauth_lab.core.tokens import ClaimsBase, DecodedToken, TokenFormatError, decode_token

JWKS_MIN_REFETCH_SECONDS = 60.0  # §11.4: no more than once per minute per issuer
JWKS_MAX_AGE_SECONDS = 24 * 3600.0


class DiscoveryErrorCode(StrEnum):
    ISSUER_MISSING = "issuer_missing"
    ISSUER_MISMATCH = "issuer_mismatch"
    UNKNOWN_KEY = "unknown_key"
    EGRESS_DENIED = "egress_denied"


class DiscoveryError(Exception):
    def __init__(self, code: DiscoveryErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class _Entry:
    metadata: JsonObject
    keys: Jwks
    fetched_at: float


type EgressPolicy = Callable[[ServerId], bool]


class KeyResolver:
    def __init__(self, http: httpx.AsyncClient, admit: EgressPolicy) -> None:
        self._http = http
        self._admit = admit
        self._cache: dict[tuple[ServerId, str], _Entry] = {}

    async def metadata(self, iss: ServerId, dwk: str) -> JsonObject:
        return (await self._entry(iss, dwk, force=False)).metadata

    async def key_for(self, iss: ServerId, dwk: str, kid: str) -> Jwk:
        entry = await self._entry(iss, dwk, force=False)
        key = _find(entry.keys, kid)
        if key is None and time.monotonic() - entry.fetched_at >= JWKS_MIN_REFETCH_SECONDS:
            entry = await self._entry(iss, dwk, force=True)
            key = _find(entry.keys, kid)
        if key is None:
            raise DiscoveryError(DiscoveryErrorCode.UNKNOWN_KEY, f"{iss} has no key {kid!r}")
        return key

    async def _entry(self, iss: ServerId, dwk: str, *, force: bool) -> _Entry:
        cached = self._cache.get((iss, dwk))
        if (
            cached is not None
            and not force
            and time.monotonic() - cached.fetched_at < JWKS_MAX_AGE_SECONDS
        ):
            return cached
        if not self._admit(iss):
            # Egress admission (§11.4): never fetch from an issuer we were not told to trust.
            raise DiscoveryError(DiscoveryErrorCode.EGRESS_DENIED, f"{iss} is not admitted")
        response = await self._http.get(f"{iss}/.well-known/{dwk}")
        response.raise_for_status()
        metadata = parse_json_object(response.content)
        issuer = metadata.get("issuer")
        if issuer is None:
            raise DiscoveryError(DiscoveryErrorCode.ISSUER_MISSING, f"{iss}/{dwk}")
        if issuer != iss:
            raise DiscoveryError(DiscoveryErrorCode.ISSUER_MISMATCH, f"{issuer!r} != {iss!r}")
        jwks_uri = metadata.get("jwks_uri")
        if not isinstance(jwks_uri, str):
            raise DiscoveryError(DiscoveryErrorCode.UNKNOWN_KEY, f"{iss} publishes no jwks_uri")
        jwks_response = await self._http.get(jwks_uri)
        jwks_response.raise_for_status()
        entry = _Entry(metadata, Jwks.model_validate_json(jwks_response.content), time.monotonic())
        self._cache[(iss, dwk)] = entry
        return entry


def _find(jwks: Jwks, kid: str) -> Jwk | None:
    return next((k for k in jwks.keys if k.kid == kid), None)


class JwtErrorCode(StrEnum):
    INVALID = "invalid"
    EXPIRED = "expired"


class JwtVerificationError(Exception):
    def __init__(self, code: JwtErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


async def verify_jwt[C: ClaimsBase](
    raw: str, claims_type: type[C], resolver: KeyResolver
) -> DecodedToken[C]:
    """Common JWT verification (§11.5.2): typ, dwk, issuer key, signature, exp."""
    try:
        decoded = decode_token(raw, claims_type)
    except TokenFormatError as e:
        raise JwtVerificationError(JwtErrorCode.INVALID, str(e)) from e
    claims = decoded.claims
    try:
        key = await resolver.key_for(claims.iss, claims.dwk, decoded.header.kid)
    except DiscoveryError as e:
        raise JwtVerificationError(JwtErrorCode.INVALID, str(e)) from e
    if not decoded.verify_with(key):
        raise JwtVerificationError(JwtErrorCode.INVALID, "JWT signature does not verify")
    if claims.remaining() <= 0:
        raise JwtVerificationError(JwtErrorCode.EXPIRED, f"{claims.jti} expired")
    return decoded
