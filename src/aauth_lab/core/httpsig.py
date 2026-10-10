"""HTTP Message Signatures profile for AAuth (§11.3, RFC 9421).

The agent signs every request; the key is conveyed by a JWT in ``Signature-Key``
(``sig=jwt;jwt="..."``). Which JWT it carries — agent, person or auth token — is
what tells the recipient *who* is asking and *what* they hold.
"""

import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from aauth_lab.core import sfv
from aauth_lab.core.encoding import sha256
from aauth_lab.core.keys import Jwk, SigningKey

LABEL = "sig"
BASE_COMPONENTS = ("@method", "@authority", "@path", "signature-key")
BODY_COMPONENTS = ("content-digest", "content-type")  # §11.3.3.1, requests with a body
DEFAULT_WINDOW_SECONDS = 60


class SignatureErrorCode(StrEnum):
    """Values of the Signature-Error header (I-D.hardt-httpbis-signature-key)."""

    INVALID_SIGNATURE = "invalid_signature"
    INVALID_INPUT = "invalid_input"
    CLOCK_SKEW = "clock_skew"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    UNSUPPORTED_ALGORITHM = "unsupported_algorithm"
    INVALID_KEY = "invalid_key"
    INVALID_JWT = "invalid_jwt"
    EXPIRED_JWT = "expired_jwt"
    UNKNOWN_KEY = "unknown_key"


class SignatureFailure(Exception):
    """Any failure here is answered with 401 + Signature-Error (§11.3.4)."""

    def __init__(
        self,
        code: SignatureErrorCode,
        detail: str,
        required_input: tuple[str, ...] = (),
    ) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.required_input = required_input

    def header_value(self) -> str:
        members: dict[str, sfv.Member] = {"error": sfv.Item(sfv.Token(self.code))}
        if self.required_input:
            members["required_input"] = sfv.InnerList(
                tuple(sfv.Item(c) for c in self.required_input)
            )
        return sfv.serialize_dictionary(members)


@dataclass(frozen=True)
class RequestParts:
    """The parts of an HTTP request that a signature can cover. Header names are lowercase."""

    method: str
    authority: str
    path: str
    headers: Mapping[str, str]
    body: bytes

    def component(self, name: str) -> str:
        match name:
            case "@method":
                return self.method.upper()
            case "@authority":
                return self.authority.lower()
            case "@path":
                return self.path or "/"
            case _:
                value = self.headers.get(name)
                if value is None:
                    raise SignatureFailure(
                        SignatureErrorCode.INVALID_INPUT, f"covered header {name!r} is absent"
                    )
                return value.strip()


def content_digest(body: bytes) -> str:
    """RFC 9530 Content-Digest with sha-256."""
    return sfv.serialize_dictionary({"sha-256": sfv.Item(sha256(body))})


def signature_key_header(token: str) -> str:
    return sfv.serialize_dictionary({LABEL: sfv.Item(sfv.Token("jwt"), {"jwt": token})})


def _signature_params(covered: tuple[str, ...], created: int) -> str:
    return sfv.serialize_member(
        sfv.InnerList(tuple(sfv.Item(c) for c in covered), {"created": created})
    )


def _signature_base(parts: RequestParts, covered: tuple[str, ...], params: str) -> bytes:
    """RFC 9421 §2.5."""
    lines = [f'"{name}": {parts.component(name)}' for name in covered]
    lines.append(f'"@signature-params": {params}')
    return "\n".join(lines).encode()


def sign(parts: RequestParts, key: SigningKey, created: int | None = None) -> dict[str, str]:
    """Return the Signature-Input and Signature headers for ``parts``.

    ``parts.headers`` must already contain Signature-Key, and Content-Digest /
    Content-Type when there is a body.
    """
    covered = BASE_COMPONENTS + (BODY_COMPONENTS if parts.body else ())
    params = _signature_params(covered, int(time.time()) if created is None else created)
    signature = key.sign(_signature_base(parts, covered, params))
    return {
        "signature-input": f"{LABEL}={params}",
        "signature": sfv.serialize_dictionary({LABEL: sfv.Item(signature)}),
    }


@dataclass(frozen=True)
class ParsedSignature:
    """A structurally valid signature. The key comes from ``token``; nothing is verified yet."""

    token: str
    covered: tuple[str, ...]
    created: int
    params: str
    signature: bytes


def parse(parts: RequestParts) -> ParsedSignature:
    """§11.3.4 steps 1-4: presence, covered components, created window, scheme."""
    raw_input = parts.headers.get("signature-input")
    raw_signature = parts.headers.get("signature")
    raw_key = parts.headers.get("signature-key")
    if raw_input is None or raw_signature is None or raw_key is None:
        raise SignatureFailure(SignatureErrorCode.INVALID_SIGNATURE, "missing signature headers")
    try:
        inputs = sfv.parse_dictionary(raw_input)
        signatures = sfv.parse_dictionary(raw_signature)
        keys = sfv.parse_dictionary(raw_key)
    except sfv.StructuredFieldError as e:
        raise SignatureFailure(SignatureErrorCode.INVALID_SIGNATURE, str(e)) from e

    signature_input = inputs.get(LABEL)
    signature = signatures.get(LABEL)
    key_member = keys.get(LABEL)
    if not isinstance(signature_input, sfv.InnerList) or not isinstance(signature, sfv.Item):
        raise SignatureFailure(SignatureErrorCode.INVALID_SIGNATURE, f"no {LABEL!r} signature")
    if not isinstance(signature.value, bytes):
        raise SignatureFailure(SignatureErrorCode.INVALID_SIGNATURE, "signature is not bytes")

    covered = tuple(i.value for i in signature_input.items if isinstance(i.value, str))
    required = BASE_COMPONENTS + (BODY_COMPONENTS if parts.body else ())
    missing = tuple(c for c in required if c not in covered)
    if missing:
        raise SignatureFailure(
            SignatureErrorCode.INVALID_INPUT, "required components not covered", required
        )

    created = sfv.int_param(signature_input.params, "created")
    if created is None:
        raise SignatureFailure(SignatureErrorCode.INVALID_SIGNATURE, "created is missing")
    age = time.time() - created
    if age > DEFAULT_WINDOW_SECONDS:
        raise SignatureFailure(SignatureErrorCode.INVALID_SIGNATURE, "created is too old")
    if -age > DEFAULT_WINDOW_SECONDS:
        raise SignatureFailure(SignatureErrorCode.CLOCK_SKEW, "created is in the future")

    # §11.3.2: agents MUST use the jwt scheme.
    if not isinstance(key_member, sfv.Item) or key_member.value != sfv.Token("jwt"):
        raise SignatureFailure(SignatureErrorCode.UNSUPPORTED_SCHEME, "only the jwt scheme")
    token = sfv.string_param(key_member, "jwt")
    if token is None:
        raise SignatureFailure(SignatureErrorCode.INVALID_JWT, "jwt parameter missing")

    if parts.body:
        _check_content_digest(parts)

    return ParsedSignature(
        token=token,
        covered=covered,
        created=created,
        params=sfv.serialize_member(signature_input),
        signature=signature.value,
    )


def _check_content_digest(parts: RequestParts) -> None:
    try:
        digests = sfv.parse_dictionary(parts.headers.get("content-digest", ""))
    except sfv.StructuredFieldError as e:
        raise SignatureFailure(SignatureErrorCode.INVALID_SIGNATURE, str(e)) from e
    digest = digests.get("sha-256")
    if not isinstance(digest, sfv.Item) or digest.value != sha256(parts.body):
        raise SignatureFailure(SignatureErrorCode.INVALID_SIGNATURE, "content-digest mismatch")


def verify(parsed: ParsedSignature, parts: RequestParts, key: Jwk) -> None:
    """§11.3.4 step 7. ``key`` is the cnf.jwk of the verified Signature-Key JWT."""
    base = _signature_base(parts, parsed.covered, parsed.params)
    if not key.verify(parsed.signature, base):
        raise SignatureFailure(SignatureErrorCode.INVALID_SIGNATURE, "signature does not verify")
