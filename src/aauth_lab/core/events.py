"""A shared timeline of who decided what, and where an operation stopped.

This is the lab's instrument, not part of AAuth: every role appends JSON lines to the
same file so one run can be read (or visualised) as a single sequence.
"""

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from aauth_lab.core.encoding import JsonObject, parse_json_object


class Actor(StrEnum):
    AGENT = "agent"
    AGENT_PROVIDER = "agent_provider"
    PERSON_SERVER = "person_server"
    RESOURCE = "resource"
    PERSON = "person"


class Kind(StrEnum):
    REQUEST = "request"
    """An HTTP call leaves a party."""
    CHALLENGE = "challenge"
    """A party refuses to serve until it is shown something more (AAuth-Requirement)."""
    DECISION = "decision"
    """A party judges: grant, deny, or escalate to someone else."""
    HOLD = "hold"
    """An operation is stopped. ``detail.where`` names who holds it."""
    RESUME = "resume"
    """A held operation continues."""
    EXECUTE = "execute"
    """The side effect actually happens."""
    TOKEN = "token"
    """A token is issued."""
    REJECT = "reject"
    """A request is refused outright."""
    INFO = "info"


@dataclass(frozen=True)
class Event:
    actor: Actor
    kind: Kind
    title: str
    detail: JsonObject = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    spec: str | None = None
    """The section of draft-hardt-oauth-aauth-protocol-11 this step follows."""


class EventLog:
    def __init__(self, path: Path | None, actor: Actor, *, echo: bool = False) -> None:
        self._path = path
        self._actor = actor
        self._echo = echo
        self._lock = threading.Lock()

    def emit(
        self,
        kind: Kind,
        title: str,
        detail: JsonObject | None = None,
        *,
        spec: str | None = None,
        actor: Actor | None = None,
    ) -> Event:
        event = Event(actor or self._actor, kind, title, detail or {}, spec=spec)
        line = json.dumps(asdict(event), ensure_ascii=False)
        if self._path is not None:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                # O_APPEND keeps whole lines intact across the role processes.
                fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
                try:
                    os.write(fd, (line + "\n").encode())
                finally:
                    os.close(fd)
        if self._echo:
            print(line, flush=True)
        return event


def read_events(path: Path) -> list[JsonObject]:
    if not path.exists():
        return []
    return [parse_json_object(line.encode()) for line in path.read_text().splitlines() if line]
