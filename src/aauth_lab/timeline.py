"""Render the shared event log as a terminal timeline."""

import sys
from pathlib import Path

from aauth_lab.core.encoding import JsonObject
from aauth_lab.core.events import Actor, Kind, read_events

_ACTOR_LABEL = {
    Actor.AGENT: ("Agent", "36"),
    Actor.AGENT_PROVIDER: ("AP", "90"),
    Actor.PERSON_SERVER: ("PS", "35"),
    Actor.RESOURCE: ("Resource", "34"),
    Actor.PERSON: ("Person", "33"),
}

_KIND_MARK = {
    Kind.REQUEST: "→",
    Kind.CHALLENGE: "⚑",
    Kind.DECISION: "◆",
    Kind.HOLD: "■",
    Kind.RESUME: "▶",
    Kind.EXECUTE: "✔",
    Kind.TOKEN: "🔑",
    Kind.REJECT: "✖",
    Kind.INFO: "·",
}


def _color(code: str, text: str, enabled: bool) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if enabled else text


def render(events: list[JsonObject], *, color: bool) -> str:
    lines: list[str] = []
    start = next((e["ts"] for e in events if isinstance(e.get("ts"), float)), 0.0)
    for e in events:
        actor, kind = Actor(str(e["actor"])), Kind(str(e["kind"]))
        label, code = _ACTOR_LABEL[actor]
        ts = e.get("ts")
        offset = f"{ts - start:7.2f}s" if isinstance(ts, float) and isinstance(start, float) else ""
        title = str(e["title"])
        if kind in (Kind.HOLD, Kind.DECISION):
            title = _color("1", title, color)
        spec = f"  [{e['spec']}]" if e.get("spec") else ""
        lines.append(
            f"{offset} {_color(code, f'{label:>8}', color)} {_KIND_MARK[kind]} {title}"
            f"{_color('90', spec, color)}"
        )
    return "\n".join(lines)


def print_timeline(path: Path) -> None:
    print(render(read_events(path), color=sys.stdout.isatty()))
