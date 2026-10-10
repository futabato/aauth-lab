"""The four AAuth JWTs (§11.5) and a minimal Ed25519 compact JWS.

Each token type is a pydantic model whose ``Literal`` fields pin ``dwk`` so that a
token of the wrong type fails to parse. ``typ`` lives in the JOSE header and is
checked before the payload is parsed (§11.5.2 step 1, §13.11).
"""

import time
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from aauth_lab.core.encoding import JsonObject, b64url_decode, b64url_encode, canonical_json
from aauth_lab.core.ids import AgentId, Jti, MissionS256, ServerId, Sub
from aauth_lab.core.keys import Jwk, JwkThumbprint, SigningKey

type TokenTyp = Literal["aa-agent+jwt", "aa-person+jwt", "aa-resource+jwt", "aa-auth+jwt"]


class Cnf(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    jwk: Jwk


class ClaimsBase(BaseModel):
    """Claims common to every AAuth JWT (§11.5.1)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    iss: ServerId
    dwk: str
    jti: Jti
    iat: int
    exp: int

    def remaining(self, now: float | None = None) -> float:
        return self.exp - (time.time() if now is None else now)


class AgentTokenClaims(ClaimsBase):
    """§5.3.1 — issued by the agent provider, binds the agent identifier to its key."""

    dwk: Literal["aauth-agent.json"] = "aauth-agent.json"
    sub: AgentId
    cnf: Cnf
    ps: ServerId | None = None


class PersonTokenClaims(ClaimsBase):
    """§7.1.2 — "which person", for one resource. Carries no authorization."""

    dwk: Literal["aauth-person.json"] = "aauth-person.json"
    aud: ServerId
    sub: Sub
    cnf: Cnf
    mission_s256: MissionS256 | None = None
    tenant: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_authorization(cls, data: object) -> object:
        # §7.1.2: "A person token MUST NOT contain scope or account."
        if isinstance(data, dict) and ("scope" in data or "account" in data):
            raise ValueError("person token must not carry scope or account")
        return data


class ResourceTokenClaims(ClaimsBase):
    """§6.7.1 — what the resource asks for, bound to one presented token and one agent key."""

    dwk: Literal["aauth-resource.json"] = "aauth-resource.json"
    aud: ServerId
    ps: ServerId
    sub: Sub
    presented_jti: Jti
    agent_jkt: JwkThumbprint
    scope: str | None = None
    mission_s256: MissionS256 | None = None
    tenant: str | None = None


class AuthTokenClaims(ClaimsBase):
    """§9.4.1 — what is authorized. Issued by the PS in three-party mode."""

    dwk: Literal["aauth-person.json", "aauth-access.json"]
    aud: ServerId
    ps: ServerId
    sub: Sub
    cnf: Cnf
    scope: str | None = None
    mission_s256: MissionS256 | None = None
    tenant: str | None = None


type AnyClaims = AgentTokenClaims | PersonTokenClaims | ResourceTokenClaims | AuthTokenClaims

TYP_OF: dict[type[ClaimsBase], TokenTyp] = {
    AgentTokenClaims: "aa-agent+jwt",
    PersonTokenClaims: "aa-person+jwt",
    ResourceTokenClaims: "aa-resource+jwt",
    AuthTokenClaims: "aa-auth+jwt",
}


class JoseHeader(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    alg: Literal["Ed25519"]
    typ: str
    kid: str


class TokenFormatError(ValueError):
    """The value is not a well-formed AAuth JWT of the expected type."""


def sign_token(key: SigningKey, claims: AnyClaims) -> str:
    header: JsonObject = {"alg": "Ed25519", "typ": TYP_OF[type(claims)], "kid": key.kid}
    payload = claims.model_dump_json(exclude_none=True).encode()
    signing_input = f"{b64url_encode(canonical_json(header))}.{b64url_encode(payload)}"
    signature = key.sign(signing_input.encode("ascii"))
    return f"{signing_input}.{b64url_encode(signature)}"


@dataclass(frozen=True)
class DecodedToken[C: ClaimsBase]:
    """A JWT whose structure and typ are valid but whose signature is NOT yet verified."""

    raw: str
    header: JoseHeader
    claims: C
    signing_input: bytes
    signature: bytes

    def verify_with(self, jwk: Jwk) -> bool:
        return jwk.verify(self.signature, self.signing_input)


def peek_typ(raw: str) -> str:
    """Read ``typ`` without trusting anything else — used to route a Signature-Key JWT."""
    try:
        return JoseHeader.model_validate_json(b64url_decode(raw.split(".")[0])).typ
    except (ValidationError, ValueError, IndexError) as e:
        raise TokenFormatError(str(e)) from e


def decode_token[C: ClaimsBase](raw: str, claims_type: type[C]) -> DecodedToken[C]:
    parts = raw.split(".")
    if len(parts) != 3:
        raise TokenFormatError("JWT must have three segments")
    try:
        header = JoseHeader.model_validate_json(b64url_decode(parts[0]))
        if header.typ != TYP_OF[claims_type]:
            raise TokenFormatError(f"typ {header.typ!r} is not {TYP_OF[claims_type]!r}")
        claims = claims_type.model_validate_json(b64url_decode(parts[1]))
        signature = b64url_decode(parts[2])
    except (ValidationError, ValueError) as e:
        raise TokenFormatError(str(e)) from e
    return DecodedToken(raw, header, claims, f"{parts[0]}.{parts[1]}".encode("ascii"), signature)


def lifetime(seconds: int, *, cap: int | None = None, now: int | None = None) -> tuple[int, int]:
    """(iat, exp) for a new token, never outliving ``cap`` (the exp it must not exceed)."""
    iat = int(time.time()) if now is None else now
    exp = iat + seconds
    return iat, exp if cap is None else min(exp, cap)


def check_not_expired(claims: ClaimsBase, now: float | None = None) -> bool:
    """§11.5.2 step 3: expired the moment the verifier's clock passes exp; no skew tolerance."""
    return claims.remaining(now) > 0


def same_holder(a: Cnf, b: Jwk) -> bool:
    return a.jwk.same_key(b)
