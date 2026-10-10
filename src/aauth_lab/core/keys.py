"""Ed25519 keys and their JWK representation.

§11.3.1: every party MUST support Ed25519; ``alg`` MUST be present and fully specified
(``Ed25519``, never the polymorphic ``EdDSA``). This lab implements Ed25519 only.
"""

import secrets
from dataclasses import dataclass
from typing import Literal, NewType

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import BaseModel, ConfigDict

from aauth_lab.core.encoding import JsonObject, b64url_decode, b64url_encode, canonical_json, sha256

JwkThumbprint = NewType("JwkThumbprint", str)
KeyId = NewType("KeyId", str)


class Jwk(BaseModel):
    """An OKP/Ed25519 public JWK. Literal fields make a missing or polymorphic alg a parse error."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    kty: Literal["OKP"]
    crv: Literal["Ed25519"]
    x: str
    alg: Literal["Ed25519"]
    kid: str | None = None

    def thumbprint(self) -> JwkThumbprint:
        """RFC 7638 JWK Thumbprint over the required members only."""
        required: JsonObject = {"crv": self.crv, "kty": self.kty, "x": self.x}
        return JwkThumbprint(b64url_encode(sha256(canonical_json(required))))

    def verify(self, signature: bytes, message: bytes) -> bool:
        public_key = Ed25519PublicKey.from_public_bytes(b64url_decode(self.x))
        try:
            public_key.verify(signature, message)
        except InvalidSignature:
            return False
        return True

    def same_key(self, other: "Jwk") -> bool:
        return self.thumbprint() == other.thumbprint()


class Jwks(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    keys: list[Jwk]


@dataclass(frozen=True)
class SigningKey:
    kid: KeyId
    private_key: Ed25519PrivateKey

    @classmethod
    def generate(cls, kid_prefix: str) -> "SigningKey":
        return cls(KeyId(f"{kid_prefix}-{secrets.token_hex(4)}"), Ed25519PrivateKey.generate())

    def public_jwk(self) -> Jwk:
        raw = self.private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return Jwk(kty="OKP", crv="Ed25519", x=b64url_encode(raw), alg="Ed25519", kid=self.kid)

    def sign(self, message: bytes) -> bytes:
        return self.private_key.sign(message)
