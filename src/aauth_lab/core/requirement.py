"""The AAuth-Requirement response header (§11.6): what a server needs before it will serve."""

from dataclasses import dataclass

from aauth_lab.core import sfv

HEADER = "AAuth-Requirement"


@dataclass(frozen=True)
class AgentTokenRequired:
    """401 — §6.1"""


@dataclass(frozen=True)
class PersonTokenRequired:
    """401 — §6.4"""


@dataclass(frozen=True)
class AuthTokenRequired:
    """401 or 202 — §6.5. Carry the resource token to the PS."""

    resource_token: str


@dataclass(frozen=True)
class InteractionRequired:
    """202 — §11.6.3. Send the person to ``url`` with ``code``."""

    url: str
    code: str


@dataclass(frozen=True)
class ApprovalPending:
    """202 — §11.6.4. Someone else is being asked; just poll."""


@dataclass(frozen=True)
class UnknownRequirement:
    """§11.6.2: an agent MUST NOT treat an unrecognized requirement as satisfiable."""

    value: str


type Requirement = (
    AgentTokenRequired
    | PersonTokenRequired
    | AuthTokenRequired
    | InteractionRequired
    | ApprovalPending
    | UnknownRequirement
)


class RequirementParseError(ValueError):
    pass


def serialize(requirement: Requirement) -> str:
    params: dict[str, sfv.BareValue]
    match requirement:
        case AgentTokenRequired():
            name, params = "agent-token", {}
        case PersonTokenRequired():
            name, params = "person-token", {}
        case AuthTokenRequired(resource_token=token):
            name, params = "auth-token", {"resource-token": token}
        case InteractionRequired(url=url, code=code):
            name, params = "interaction", {"url": url, "code": code}
        case ApprovalPending():
            name, params = "approval", {}
        case UnknownRequirement(value=value):
            name, params = value, {}
    return sfv.serialize_dictionary({"requirement": sfv.Item(sfv.Token(name), params)})


def parse(value: str) -> Requirement:
    try:
        members = sfv.parse_dictionary(value)
    except sfv.StructuredFieldError as e:
        raise RequirementParseError(str(e)) from e
    member = members.get("requirement")
    if not isinstance(member, sfv.Item) or not isinstance(member.value, sfv.Token):
        raise RequirementParseError("requirement member missing or not a token")
    kind = member.value.value
    item = member

    def param(name: str) -> str:
        found = sfv.string_param(item, name)
        if found is None:
            raise RequirementParseError(f"{kind} requires {name!r}")
        return found

    match kind:
        case "agent-token":
            return AgentTokenRequired()
        case "person-token":
            return PersonTokenRequired()
        case "auth-token":
            return AuthTokenRequired(param("resource-token"))
        case "interaction":
            return InteractionRequired(param("url"), param("code"))
        case "approval":
            return ApprovalPending()
        case other:
            return UnknownRequirement(other)
