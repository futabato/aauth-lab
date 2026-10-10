"""uvicorn factories: ``uvicorn --factory aauth_lab.serve:person_server``."""

from fastapi import FastAPI

from aauth_lab.agent_provider.app import create_app as create_agent_provider
from aauth_lab.config import Topology
from aauth_lab.person_server.app import create_app as create_person_server
from aauth_lab.resource.app import create_app as create_resource


def agent_provider() -> FastAPI:
    return create_agent_provider(Topology.from_env())


def person_server() -> FastAPI:
    return create_person_server(Topology.from_env())


def resource() -> FastAPI:
    return create_resource(Topology.from_env())
