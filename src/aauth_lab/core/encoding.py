"""Encoding helpers shared by every role: base64url, JSON values, digests."""

import base64
import hashlib
import json

from pydantic import TypeAdapter

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

_json_object_adapter: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)
_json_value_adapter: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


def b64url_encode(data: bytes) -> str:
    """Unpadded base64url (RFC 7515 §2)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def b64_encode(data: bytes) -> str:
    """Standard padded base64, as used by Structured Field byte sequences."""
    return base64.b64encode(data).decode("ascii")


def b64_decode(text: str) -> bytes:
    return base64.b64decode(text, validate=True)


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def canonical_json(value: JsonValue) -> bytes:
    """Compact JSON with sorted keys (RFC 7638 style; also used for mission blobs)."""
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()


def parse_json_object(data: bytes) -> JsonObject:
    return _json_object_adapter.validate_json(data)


def parse_json_value(data: bytes) -> JsonValue:
    return _json_value_adapter.validate_json(data)
