import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI

from aauth_lab.agent_provider.app import create_app as create_agent_provider
from aauth_lab.config import StepUpDelivery, Topology
from aauth_lab.core.ids import AgentId, ServerId
from aauth_lab.person_server.app import create_app as create_person_server
from aauth_lab.resource.app import create_app as create_resource


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:  # running in a thread
        pass


def _serve(app: FastAPI, port: int) -> _Server:
    server = _Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.02)
    return server


@pytest.fixture(scope="session")
def lab(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Topology]:
    ports = [_free_port() for _ in range(3)]
    topology = Topology(
        agent_provider=ServerId(f"http://localhost:{ports[0]}"),
        person_server=ServerId(f"http://localhost:{ports[1]}"),
        resource=ServerId(f"http://localhost:{ports[2]}"),
        agent=AgentId("aauth:doc-assistant@localhost"),
        events_path=Path(tmp_path_factory.mktemp("lab")) / "events.jsonl",
        step_up_delivery=StepUpDelivery.DEFERRED,
    )
    servers = [
        _serve(create_agent_provider(topology), ports[0]),
        _serve(create_person_server(topology), ports[1]),
        _serve(create_resource(topology), ports[2]),
    ]
    yield topology
    for s in servers:
        s.should_exit = True
