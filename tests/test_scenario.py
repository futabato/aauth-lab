"""Scenario A end to end: who decides, and where the operation stops."""

import httpx
import pytest

from aauth_lab.agent.client import Done, InteractionPrompt, Refused, enroll
from aauth_lab.config import StepUpDelivery, Topology
from aauth_lab.core.discovery import KeyResolver
from aauth_lab.core.encoding import JsonObject
from aauth_lab.core.events import Actor, EventLog, Kind, read_events
from aauth_lab.core.tokens import AuthTokenClaims, decode_token
from aauth_lab.person import PersonChoice, person
from aauth_lab.scenario import DemoOptions, run_demo

pytestmark = pytest.mark.anyio


async def _doc_ids(lab: Topology) -> set[int]:
    async with httpx.AsyncClient() as http:
        docs = (await http.get(f"{lab.resource}/lab/docs")).json()
    return {d["id"] for d in docs}


def _events(lab: Topology) -> list[JsonObject]:
    return read_events(lab.events_path)


def _holds(lab: Topology) -> list[str]:
    """Where each HOLD event says the operation was stopped."""
    wheres = []
    for e in _events(lab):
        detail = e.get("detail")
        if e["kind"] == Kind.HOLD and isinstance(detail, dict):
            wheres.append(str(detail.get("where")))
    return wheres


@pytest.fixture(autouse=True)
def _fresh_events(lab: Topology) -> None:
    lab.events_path.write_text("")


async def test_deferred_step_up_is_held_by_resource_and_run_once(lab: Topology) -> None:
    report = await run_demo(lab, DemoOptions(delivery=StepUpDelivery.DEFERRED))

    assert isinstance(report.outcome("list"), Done)
    delete = report.outcome("delete")
    assert delete == Done(200, {"deleted": 3, "title": "古い下書き (2019)"})
    # Re-presenting the same auth token is answered from the stored result (§6.5.1).
    assert report.outcome("replay") == delete
    assert (
        sum(1 for e in _events(lab) if e["kind"] == Kind.EXECUTE and "削除" in str(e["title"])) == 1
    )
    # A valid token is necessary but not sufficient: the resource's own rule still applies.
    assert report.outcome("protected") == Refused(
        Actor.RESOURCE, "protected", "雇用契約書 is protected"
    )
    assert await _doc_ids(lab) == {1, 2, 4}
    # The DELETE was held by the resource, while the token request was held by the PS.
    assert "resource" in _holds(lab)
    assert "person_server" in _holds(lab)


async def test_retry_step_up_keeps_nothing_at_resource(lab: Topology) -> None:
    report = await run_demo(lab, DemoOptions(delivery=StepUpDelivery.RETRY))

    assert report.outcome("delete") == Done(200, {"deleted": 3, "title": "古い下書き (2019)"})
    assert "resource" not in _holds(lab)
    assert "replay" not in dict(report.steps)


async def test_person_denies(lab: Topology) -> None:
    report = await run_demo(lab, DemoOptions(person=PersonChoice.DENY))

    assert report.outcome("delete") == Refused(
        Actor.PERSON_SERVER, "denied", "The person declined the request."
    )
    assert 3 in await _doc_ids(lab)


async def test_person_narrows_the_grant(lab: Topology) -> None:
    report = await run_demo(lab, DemoOptions(person=PersonChoice.NARROW))

    assert report.outcome("delete") == Refused(Actor.RESOURCE, "insufficient_scope")
    assert 3 in await _doc_ids(lab)


async def test_mission_terminated_mid_task(lab: Topology) -> None:
    report = await run_demo(lab, DemoOptions(revoke_mission_before_delete=True))

    assert isinstance(report.outcome("list"), Done)
    delete = report.outcome("delete")
    assert isinstance(delete, Refused)
    assert (delete.by, delete.error) == (Actor.PERSON_SERVER, "mission_terminated")
    assert 3 in await _doc_ids(lab)


async def test_step_up_token_inherits_exp_of_presented_token(lab: Topology) -> None:
    """§9.4.1 / §7.1.3: an auth token issued on a step-up cannot outlive the token it replaced."""
    async with httpx.AsyncClient(timeout=30) as http:
        await http.post(f"{lab.resource}/lab/reset")
        log = EventLog(lab.events_path, Actor.AGENT)
        agent = await enroll(
            lab.agent_provider,
            http,
            KeyResolver(http, lab.admits),
            log,
            person(http, PersonChoice.APPROVE),
        )
        await agent.propose_mission("整理", [lab.resource])
        assert isinstance(await agent.call("GET", f"{lab.resource}/docs"), Done)
        first = decode_token(agent.auth_tokens[lab.resource], AuthTokenClaims).claims

        assert isinstance(await agent.call("DELETE", f"{lab.resource}/docs/2"), Done)
        second = decode_token(agent.auth_tokens[lab.resource], AuthTokenClaims).claims

    assert second.jti != first.jti
    assert second.scope == "docs.delete docs.read"
    assert second.exp <= first.exp


async def test_consent_is_remembered_within_mission(lab: Topology) -> None:
    """§6.7.1: the PS SHOULD NOT re-prompt for the same resource and scope in a mission."""
    prompts: list[str] = []
    async with httpx.AsyncClient(timeout=30) as http:
        await http.post(f"{lab.resource}/lab/reset")
        approve = person(http, PersonChoice.APPROVE)

        async def counting(prompt: InteractionPrompt) -> None:
            prompts.append(prompt.reason)
            await approve(prompt)

        agent = await enroll(
            lab.agent_provider,
            http,
            KeyResolver(http, lab.admits),
            EventLog(lab.events_path, Actor.AGENT),
            counting,
        )
        await agent.propose_mission("整理", [lab.resource])
        assert isinstance(await agent.call("DELETE", f"{lab.resource}/docs/2"), Done)
        # Drop the broad token so the next delete starts from the person token again.
        del agent.auth_tokens[lab.resource]
        assert isinstance(await agent.call("DELETE", f"{lab.resource}/docs/3"), Done)

    assert len(prompts) == 2  # mission approval + the first docs.delete only
