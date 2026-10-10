"""Where each role lives in the lab, and lab-only relaxations of the spec."""

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from aauth_lab.core.ids import AgentId, ServerId, agent_id, server_id


class StepUpDelivery(StrEnum):
    """§6.5.1: "Which delivery to use is the resource's choice, per invocation." """

    RETRY = "retry"
    """401 — the resource keeps nothing; the agent must send the request again."""
    DEFERRED = "deferred"
    """202 — the resource holds the invocation and runs it on the first poll with an auth token."""


@dataclass(frozen=True)
class Topology:
    agent_provider: ServerId
    person_server: ServerId
    resource: ServerId
    agent: AgentId
    events_path: Path
    step_up_delivery: StepUpDelivery

    def admits(self, issuer: ServerId) -> bool:
        """Egress admission (§11.4): only the lab's own servers are ever fetched."""
        return issuer in (self.agent_provider, self.person_server, self.resource)

    @classmethod
    def from_env(cls) -> "Topology":
        def url(name: str, port: int) -> ServerId:
            value = os.environ.get(name, f"http://localhost:{port}")
            return server_id(value, allow_loopback_http=True)

        return cls(
            agent_provider=url("AAUTH_LAB_AP", 8001),
            person_server=url("AAUTH_LAB_PS", 8002),
            resource=url("AAUTH_LAB_RESOURCE", 8003),
            agent=agent_id(os.environ.get("AAUTH_LAB_AGENT", "aauth:doc-assistant@localhost")),
            events_path=Path(os.environ.get("AAUTH_LAB_EVENTS", "var/events.jsonl")),
            step_up_delivery=StepUpDelivery(
                os.environ.get("AAUTH_LAB_STEP_UP", StepUpDelivery.DEFERRED)
            ),
        )
