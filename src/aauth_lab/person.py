"""Stand-ins for the person at the PS consent page.

In a real deployment the person reads the page and clicks. For scripted runs and tests
these handlers do the same over HTTP; ``manual`` hands the link to a human instead.
"""

import re
import webbrowser
from enum import StrEnum

import httpx

from aauth_lab.agent.client import InteractionHandler, InteractionPrompt
from aauth_lab.core.ids import Scope


class PersonChoice(StrEnum):
    APPROVE = "approve"
    DENY = "deny"
    NARROW = "narrow"
    """Approve, but untick every scope outside ``keep`` (§11.10: the PS may narrow)."""
    IGNORE = "ignore"
    """Never open the page — the request expires at the PS."""
    MANUAL = "manual"


_FORM = re.compile(r'action="/interaction/([^"/]+)/decision"')
_NONCE = re.compile(r'name="nonce" value="([^"]+)"')
_SCOPE = re.compile(r'name="scope" value="([^"]+)"')


async def decide_on_page(
    http: httpx.AsyncClient, prompt: InteractionPrompt, choice: PersonChoice, keep: Scope
) -> None:
    page = await http.get(prompt.url, params={"code": prompt.code})
    page.raise_for_status()
    form, nonce = _FORM.search(page.text), _NONCE.search(page.text)
    if form is None or nonce is None:
        raise RuntimeError(f"no consent form at {prompt.link}")
    offered = _SCOPE.findall(page.text)
    scopes = [s for s in offered if choice is not PersonChoice.NARROW or s in keep]
    decision = "deny" if choice is PersonChoice.DENY else "approve"
    origin = str(page.url.copy_with(path="/", query=None)).rstrip("/")
    response = await http.post(
        f"{origin}/interaction/{form.group(1)}/decision",
        data={"decision": decision, "nonce": nonce.group(1), "scope": scopes},
    )
    response.raise_for_status()


def person(
    http: httpx.AsyncClient,
    choice: PersonChoice,
    *,
    mission_choice: PersonChoice = PersonChoice.APPROVE,
    keep: Scope = frozenset({"docs.read"}),
) -> InteractionHandler:
    """Build the handler the agent calls when the PS needs the person.

    The first prompt of a run is the mission approval; ``mission_choice`` answers it,
    ``choice`` answers every later one.
    """
    seen = 0

    async def handle(prompt: InteractionPrompt) -> None:
        nonlocal seen
        current = mission_choice if seen == 0 else choice
        seen += 1
        match current:
            case PersonChoice.MANUAL:
                print(
                    f"\n  >>> 本人の判断が必要です（{prompt.reason}）\n"
                    f"  >>> ブラウザで開いてください: {prompt.link}\n"
                    f"  >>> 確認コード: {prompt.code}\n",
                    flush=True,
                )
                webbrowser.open(prompt.link)
            case PersonChoice.IGNORE:
                pass
            case _:
                await decide_on_page(http, prompt, current, keep)

    return handle
