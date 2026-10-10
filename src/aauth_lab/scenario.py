"""Scenario A: an agent needs more permission in the middle of its work.

1. The agent proposes a mission ("tidy up my old documents"); the person approves it.
2. It lists documents — ``docs.read`` is low-risk and pre-approved by the mission,
   so the PS grants it without asking anyone.
3. It deletes an old draft — ``docs.delete`` is a step-up. The resource stops the
   operation (holds it, or drops it), the PS judges it needs the person, the person
   decides, and only then does the deletion run.
4. It re-polls with the same auth token — the resource answers from its stored result.
5. It tries to delete a protected document — the token allows it, the resource refuses.
"""

from dataclasses import dataclass, field

import httpx

from aauth_lab.agent.client import Agent, Done, Outcome, enroll
from aauth_lab.config import StepUpDelivery, Topology
from aauth_lab.core.discovery import KeyResolver
from aauth_lab.core.encoding import JsonObject
from aauth_lab.core.events import Actor, EventLog, Kind
from aauth_lab.person import PersonChoice, person

MISSION = (
    "# 古い文書の整理\n\n"
    "Lab Docs にある文書を確認し、長期間使われていない古い下書きを整理する。"
    "削除する前に、対象を本人に確認すること。"
)


@dataclass(frozen=True)
class DemoOptions:
    delivery: StepUpDelivery = StepUpDelivery.DEFERRED
    person: PersonChoice = PersonChoice.APPROVE
    revoke_mission_before_delete: bool = False


@dataclass
class DemoReport:
    steps: list[tuple[str, Outcome]] = field(default_factory=list)

    def outcome(self, label: str) -> Outcome:
        return next(o for name, o in self.steps if name == label)


async def run_demo(topology: Topology, options: DemoOptions) -> DemoReport:
    resource, ps = topology.resource, topology.person_server
    report = DemoReport()
    async with httpx.AsyncClient(timeout=60) as http:
        await http.post(f"{resource}/lab/reset")
        await http.put(f"{resource}/lab/settings", json={"step_up_delivery": options.delivery})

        log = EventLog(topology.events_path, Actor.AGENT)
        settings: JsonObject = {
            "delivery": options.delivery.value,
            "person": options.person.value,
            "revoke_mission_before_delete": options.revoke_mission_before_delete,
        }
        log.emit(Kind.INFO, "=== シナリオ A: 実行途中の追加許可 ===", settings)

        agent: Agent = await enroll(
            topology.agent_provider,
            http,
            KeyResolver(http, topology.admits),
            log,
            person(http, options.person),
        )
        mission = await agent.propose_mission(MISSION, [resource])

        report.steps.append(("list", await agent.call("GET", f"{resource}/docs")))

        if options.revoke_mission_before_delete:
            log.emit(Kind.INFO, "（実験）本人が mission を途中で終了させる", actor=Actor.PERSON)
            await http.post(f"{ps}/lab/missions/{mission}/revoke")

        delete = await agent.call(
            "DELETE",
            f"{resource}/docs/3",
            justification="「古い下書き (2019)」は 6 年以上更新がなく、mission の整理対象に当たるため削除したい。",
        )
        report.steps.append(("delete", delete))

        if isinstance(delete, Done) and agent.last_hold:
            log.emit(Kind.INFO, "（実験）応答が失われた想定で、同じ auth token で再 poll する")
            report.steps.append(("replay", await agent.repoll(agent.last_hold, resource)))

        if isinstance(delete, Done):
            protected = await agent.call(
                "DELETE",
                f"{resource}/docs/4",
                justification="（実験）保護された文書も削除を試みる。",
            )
            report.steps.append(("protected", protected))

        log.emit(Kind.INFO, "=== シナリオ終了 ===")
    return report
