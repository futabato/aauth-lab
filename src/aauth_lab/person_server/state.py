"""Person Server state: missions (§8) and pending requests (§11.8)."""

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from aauth_lab.core.encoding import JsonObject, b64url_encode, canonical_json, sha256
from aauth_lab.core.ids import AgentId, MissionS256, Scope, ServerId
from aauth_lab.core.keys import Jwk
from aauth_lab.core.tokens import ResourceTokenClaims

PENDING_LIFETIME_SECONDS = 600
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class MissionBlob(BaseModel):
    """The approved mission (§8.2). Its exact persisted bytes are what s256 covers."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    agent: AgentId
    approved_at: str
    description: str
    approved_resources: list[ServerId] = []
    expires_at: str | None = None


class TerminationReason(StrEnum):
    """§8.6"""

    COMPLETED = "completed"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass
class Mission:
    s256: MissionS256
    raw: bytes
    blob: MissionBlob
    terminated: TerminationReason | None = None
    consents: dict[ServerId, Scope] = field(default_factory=dict)
    """Remembered consent decisions within the mission (§6.7.1: SHOULD NOT re-prompt)."""
    log: list[JsonObject] = field(default_factory=list)

    @classmethod
    def approve(cls, blob: MissionBlob) -> "Mission":
        raw = canonical_json(blob.model_dump(mode="json", exclude_none=True))
        return cls(MissionS256(b64url_encode(sha256(raw))), raw, blob)

    @property
    def active(self) -> bool:
        return self.terminated is None


class PendingState(StrEnum):
    PENDING = "pending"
    INTERACTING = "interacting"
    """§11.8.2: the person has reached the interaction page."""
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    GONE = "gone"
    """A terminal answer was already delivered; the pending URL now returns 410 (§13.2)."""


@dataclass(frozen=True)
class MissionProposal:
    description: str
    resources: tuple[ServerId, ...]


@dataclass(frozen=True)
class TokenRequest:
    resource_token: ResourceTokenClaims
    requested: Scope
    justification: str | None
    supervisor_reason: str
    exp_cap: int
    """The auth token may not outlive this (agent token, presented token, mission)."""
    step_up: bool
    resource_name: str
    scope_descriptions: dict[str, str]


type Subject = MissionProposal | TokenRequest


@dataclass(frozen=True)
class Approval:
    """The person's answer. ``scope`` may be narrower than requested (§11.10)."""

    scope: Scope


@dataclass
class Pending:
    id: str
    agent: AgentId
    agent_key: Jwk
    agent_token_exp: int
    subject: Subject
    code: str
    expires_at: float
    state: PendingState = PendingState.PENDING
    approval: Approval | None = None
    result: JsonObject | None = None
    decision_nonce: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    def settle(self, state: PendingState) -> None:
        self.state = state
        self.changed.set()

    def refresh_expiry(self) -> None:
        if self.state in (PendingState.PENDING, PendingState.INTERACTING) and (
            time.time() > self.expires_at
        ):
            self.settle(PendingState.EXPIRED)


def new_interaction_code() -> str:
    """§11.6.3.1: ≥40 bits, Crockford base32, ≥8 symbols, displayed with a grouping hyphen."""
    symbols = "".join(secrets.choice(CROCKFORD) for _ in range(8))
    return f"{symbols[:4]}-{symbols[4:]}"


def normalize_code(value: str) -> str:
    folded = value.upper().replace("-", "").replace("I", "1").replace("L", "1").replace("O", "0")
    return "".join(c for c in folded if c in CROCKFORD)


@dataclass
class PersonServerState:
    person_name: str = "Alice"
    bindings: dict[AgentId, str] = field(default_factory=dict)
    missions: dict[MissionS256, Mission] = field(default_factory=dict)
    pendings: dict[str, Pending] = field(default_factory=dict)
    codes: dict[str, str] = field(default_factory=dict)
    """Normalized code → pending id. A code is removed once used (single use)."""

    def add_pending(
        self, agent: AgentId, agent_key: Jwk, agent_token_exp: int, subject: Subject
    ) -> Pending:
        pending = Pending(
            id=secrets.token_urlsafe(18),  # §13.2: unguessable
            agent=agent,
            agent_key=agent_key,
            agent_token_exp=agent_token_exp,
            subject=subject,
            code=new_interaction_code(),
            expires_at=time.time() + PENDING_LIFETIME_SECONDS,
        )
        self.pendings[pending.id] = pending
        self.codes[normalize_code(pending.code)] = pending.id
        return pending

    def redeem_code(self, code: str) -> Pending | None:
        pending_id = self.codes.pop(normalize_code(code), None)
        return None if pending_id is None else self.pendings.get(pending_id)

    def open_requests(self) -> list[Pending]:
        for p in self.pendings.values():
            p.refresh_expiry()
        return [
            p
            for p in self.pendings.values()
            if p.state in (PendingState.PENDING, PendingState.INTERACTING)
        ]
