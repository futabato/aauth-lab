"""The Supervisor (§4.3, §4.4): the PS-side judgement of "should this token be issued?".

The spec leaves the Supervisor's protocol TBD and lets an implementation keep it inside
the PS. Its inputs are fixed by the spec, though: user consent and, under a mission,
the mission's intent and prior log entries. This module makes that judgement an
explicit, swappable function so the lab can compare policies (rules today, an LLM later).
"""

from dataclasses import dataclass
from typing import Protocol

from aauth_lab.core.ids import AgentId, Scope, ServerId, format_scope
from aauth_lab.person_server.state import Mission


@dataclass(frozen=True)
class TokenRequestContext:
    agent: AgentId
    resource: ServerId
    requested: Scope
    """The resource token's scope: what the *resource* says is needed (resource-asserted)."""
    already_consented: Scope
    """What the person already approved for this resource within this mission (§6.7.1)."""
    mission: Mission | None
    justification: str | None
    """Why the agent says it needs it (agent-asserted, §7.4) — never sufficient on its own."""
    step_up: bool
    """True when the presented token was an auth token (the agent already held some access)."""


@dataclass(frozen=True)
class Grant:
    scope: Scope
    reason: str


@dataclass(frozen=True)
class AskPerson:
    scope: Scope
    reason: str


@dataclass(frozen=True)
class Deny:
    reason: str


type Verdict = Grant | AskPerson | Deny


class Supervisor(Protocol):
    def evaluate(self, ctx: TokenRequestContext) -> Verdict: ...


@dataclass(frozen=True)
class RuleSupervisor:
    """A deliberately simple, legible policy.

    * ``never``      — scopes the person has said no agent may ever get.
    * ``low_risk``   — granted without asking, but only at a resource the person
                       pre-approved when approving the mission.
    * anything else — the person is asked, once per mission/resource/scope.
    """

    never: Scope = frozenset({"docs.admin"})
    low_risk: Scope = frozenset({"docs.read"})

    def evaluate(self, ctx: TokenRequestContext) -> Verdict:
        forbidden = ctx.requested & self.never
        if forbidden:
            return Deny(f"{format_scope(forbidden)} は常に拒否するポリシー")

        preapproved = (
            self.low_risk
            if ctx.mission is not None and ctx.resource in ctx.mission.blob.approved_resources
            else frozenset()
        )
        covered = preapproved | ctx.already_consented
        missing = ctx.requested - covered
        if not missing:
            parts = []
            if ctx.requested & preapproved:
                parts.append(
                    f"{format_scope(ctx.requested & preapproved)} は mission で承認済みリソースの低リスク scope"
                )
            if ctx.requested & ctx.already_consented:
                parts.append(
                    f"{format_scope(ctx.requested & ctx.already_consented)} は本人がこの mission 内で同意済み"
                )
            return Grant(ctx.requested, " / ".join(parts))
        return AskPerson(
            ctx.requested,
            f"{format_scope(missing)} は本人の同意が必要"
            + ("（step-up: 既存の権限を超える要求）" if ctx.step_up else ""),
        )
