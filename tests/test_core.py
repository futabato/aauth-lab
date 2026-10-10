import time

import pytest

from aauth_lab.core import httpsig, requirement
from aauth_lab.core.httpsig import RequestParts, SignatureErrorCode, SignatureFailure
from aauth_lab.core.ids import Jti, ServerId, Sub
from aauth_lab.core.keys import SigningKey
from aauth_lab.core.tokens import (
    Cnf,
    PersonTokenClaims,
    ResourceTokenClaims,
    TokenFormatError,
    decode_token,
    sign_token,
)


def _signed(key: SigningKey, body: bytes = b"", path: str = "/token") -> RequestParts:
    headers = {"signature-key": httpsig.signature_key_header("a.b.c")}
    if body:
        headers["content-type"] = "application/json"
        headers["content-digest"] = httpsig.content_digest(body)
    parts = RequestParts("POST", "ps.example", path, headers, body)
    return RequestParts(
        parts.method, parts.authority, parts.path, {**headers, **httpsig.sign(parts, key)}, body
    )


def test_signature_round_trip_and_tamper() -> None:
    key = SigningKey.generate("t")
    parts = _signed(key, b'{"a":1}')
    parsed = httpsig.parse(parts)
    assert parsed.token == "a.b.c"
    assert "content-digest" in parsed.covered
    httpsig.verify(parsed, parts, key.public_jwk())

    moved = RequestParts(parts.method, parts.authority, "/other", parts.headers, parts.body)
    with pytest.raises(SignatureFailure) as e:
        httpsig.verify(httpsig.parse(moved), moved, key.public_jwk())
    assert e.value.code is SignatureErrorCode.INVALID_SIGNATURE

    swapped = RequestParts(parts.method, parts.authority, parts.path, parts.headers, b'{"a":2}')
    with pytest.raises(SignatureFailure):
        httpsig.parse(swapped)  # content-digest no longer matches


def test_body_must_be_covered() -> None:
    key = SigningKey.generate("t")
    unsigned_body = _signed(key)
    parts = RequestParts(
        "POST",
        "ps.example",
        "/token",
        {**unsigned_body.headers, "content-type": "application/json"},
        b"{}",
    )
    with pytest.raises(SignatureFailure) as e:
        httpsig.parse(parts)
    assert e.value.code is SignatureErrorCode.INVALID_INPUT
    assert "content-digest" in e.value.required_input


def test_person_token_cannot_carry_scope() -> None:
    key = SigningKey.generate("ps")
    now = int(time.time())
    with pytest.raises(ValueError, match="scope"):
        PersonTokenClaims.model_validate(
            {
                "iss": "https://ps.example",
                "jti": "x",
                "iat": now,
                "exp": now + 60,
                "aud": "https://r.example",
                "sub": "s",
                "cnf": {"jwk": key.public_jwk().model_dump()},
                "scope": "docs.delete",
            }
        )
    token = sign_token(
        key,
        PersonTokenClaims(
            iss=ServerId("https://ps.example"),
            jti=Jti("x"),
            iat=now,
            exp=now + 60,
            aud=ServerId("https://r.example"),
            sub=Sub("s"),
            cnf=Cnf(jwk=key.public_jwk()),
        ),
    )
    # §13.11: only typ distinguishes a person token from an auth token.
    with pytest.raises(TokenFormatError, match="typ"):
        decode_token(token, ResourceTokenClaims)
    assert decode_token(token, PersonTokenClaims).verify_with(key.public_jwk())


def test_requirement_header_round_trip() -> None:
    for need in (
        requirement.PersonTokenRequired(),
        requirement.AuthTokenRequired("eyJ.x.y"),
        requirement.InteractionRequired("https://ps.example/interaction", "ABCD-EFGH"),
    ):
        assert requirement.parse(requirement.serialize(need)) == need
    assert requirement.parse("requirement=payment-ish") == requirement.UnknownRequirement(
        "payment-ish"
    )
