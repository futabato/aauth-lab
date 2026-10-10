"""Agent Provider (§5.1): attests "this key belongs to agent X" by issuing agent tokens.

How an agent first obtains its token is out of scope for the protocol
(I-D.hardt-aauth-bootstrap); the lab uses an unauthenticated ``/lab/enroll``.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from aauth_lab.config import Topology
from aauth_lab.core.encoding import JsonObject
from aauth_lab.core.events import Actor, EventLog, Kind
from aauth_lab.core.ids import new_jti
from aauth_lab.core.keys import Jwk, Jwks, SigningKey
from aauth_lab.core.tokens import AgentTokenClaims, Cnf, lifetime, sign_token

AGENT_TOKEN_LIFETIME = 3600  # SHOULD NOT exceed 24h (§5.3.1)


class EnrollRequest(BaseModel):
    jwk: Jwk


class EnrollResponse(BaseModel):
    agent_token: str
    expires_in: int


def create_app(topology: Topology) -> FastAPI:
    app = FastAPI(title="AAuth Lab — Agent Provider")
    key = SigningKey.generate("ap")
    log = EventLog(topology.events_path, Actor.AGENT_PROVIDER)

    @app.get("/.well-known/aauth-agent.json")
    def metadata() -> JsonObject:
        return {
            "issuer": topology.agent_provider,
            "jwks_uri": f"{topology.agent_provider}/.well-known/jwks.json",
            "name": "AAuth Lab Agent Provider",
            "description": "Issues agent tokens for the lab's document assistant.",
        }

    @app.get("/.well-known/jwks.json")
    def jwks() -> Jwks:
        return Jwks(keys=[key.public_jwk()])

    @app.post("/lab/enroll")
    def enroll(request: EnrollRequest) -> EnrollResponse:
        iat, exp = lifetime(AGENT_TOKEN_LIFETIME)
        claims = AgentTokenClaims(
            iss=topology.agent_provider,
            jti=new_jti("at"),
            iat=iat,
            exp=exp,
            sub=topology.agent,
            cnf=Cnf(jwk=request.jwk),
            ps=topology.person_server,
        )
        log.emit(
            Kind.TOKEN,
            "agent token を発行",
            {"sub": claims.sub, "ps": topology.person_server, "jkt": request.jwk.thumbprint()},
            spec="§5.3",
        )
        return EnrollResponse(agent_token=sign_token(key, claims), expires_in=exp - iat)

    return app
