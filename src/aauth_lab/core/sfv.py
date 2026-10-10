"""Typed view over RFC 9651 Structured Field Dictionaries.

AAuth-Requirement, Signature-Key, Signature-Input, Signature, Signature-Error and
Content-Digest are all Dictionaries. ``http_sfv`` parses them; this module turns
its untyped containers into frozen dataclasses so the rest of the code never sees Any.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from http_sfv.dictionary import Dictionary as SfvDictionary
from http_sfv.item import InnerList as SfvInnerList
from http_sfv.item import Item as SfvItem
from http_sfv.list import List as SfvList
from http_sfv.types import BareItemType as SfvBare
from http_sfv.types import Token as SfvToken

type Bare = str | int | bool | bytes | Decimal
type Params = dict[str, Bare]


@dataclass(frozen=True)
class Token:
    """An sf-token (distinct from an sf-string on the wire)."""

    value: str


type BareValue = Bare | Token


@dataclass(frozen=True)
class Item:
    value: BareValue
    params: dict[str, BareValue] = field(default_factory=dict)


@dataclass(frozen=True)
class InnerList:
    items: tuple[Item, ...]
    params: dict[str, BareValue] = field(default_factory=dict)


type Member = Item | InnerList


class StructuredFieldError(ValueError):
    pass


def _bare_from_sfv(value: object) -> BareValue:
    if isinstance(value, SfvToken):
        return Token(str(value))
    if isinstance(value, str | int | bool | bytes | Decimal):
        return value
    raise StructuredFieldError(f"unsupported bare item: {value!r}")


def _bare_to_sfv(value: BareValue) -> SfvBare:
    return SfvToken(value.value) if isinstance(value, Token) else value


def _params_from_sfv(params: object) -> dict[str, BareValue]:
    if not isinstance(params, dict):
        raise StructuredFieldError("parameters are not a mapping")
    return {str(k): _bare_from_sfv(v) for k, v in params.items()}


def _item_from_sfv(item: object) -> Item:
    if not isinstance(item, SfvItem):
        raise StructuredFieldError("expected an item")
    return Item(_bare_from_sfv(item.value), _params_from_sfv(item.params))


def parse_dictionary(value: str) -> dict[str, Member]:
    parsed = SfvDictionary()
    try:
        parsed.parse(value.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as e:
        raise StructuredFieldError(str(e)) from e
    result: dict[str, Member] = {}
    for key, member in parsed.items():
        if isinstance(member, SfvInnerList):
            items = tuple(_item_from_sfv(i) for i in member)
            result[str(key)] = InnerList(items, _params_from_sfv(member.params))
        else:
            result[str(key)] = _item_from_sfv(member)
    return result


def parse_token_list(value: str) -> tuple[str, ...]:
    parsed = SfvList()
    try:
        parsed.parse(value.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as e:
        raise StructuredFieldError(str(e)) from e
    return tuple(
        str(m.value) for m in parsed if isinstance(m, SfvItem) and isinstance(m.value, str)
    )


def _item_to_sfv(item: Item) -> SfvItem:
    out = SfvItem(_bare_to_sfv(item.value))
    for k, v in item.params.items():
        out.params[k] = _bare_to_sfv(v)
    return out


def serialize_member(member: Member) -> str:
    if isinstance(member, Item):
        return str(_item_to_sfv(member))
    inner = SfvInnerList([_item_to_sfv(i) for i in member.items])
    for k, v in member.params.items():
        inner.params[k] = _bare_to_sfv(v)
    return str(inner)


def serialize_dictionary(members: dict[str, Member]) -> str:
    out = SfvDictionary()
    for key, member in members.items():
        if isinstance(member, Item):
            out[key] = _item_to_sfv(member)
        else:
            inner = SfvInnerList([_item_to_sfv(i) for i in member.items])
            for k, v in member.params.items():
                inner.params[k] = _bare_to_sfv(v)
            out[key] = inner
    return str(out)


def string_param(item: Item, name: str) -> str | None:
    value = item.params.get(name)
    return value if isinstance(value, str) else None


def int_param(params: dict[str, BareValue], name: str) -> int | None:
    value = params.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else None
