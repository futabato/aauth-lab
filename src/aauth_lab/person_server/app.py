"""Person Server (§7): represents the person; decides whether tokens are issued.

In the step-up flow this is where the *judgement* happens — but not where the
operation is held. The resource holds (or drops) the invocation; the PS only holds
the token request while the person decides.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import FastAPI, Form, Header, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from aauth_lab.config import Topology
from aauth_lab.core import requirement
from aauth_lab.core.discovery import (
    DiscoveryError,
    JwtErrorCode,
    JwtVerificationError,
    KeyResolver,
    verify_jwt,
)
from aauth_lab.core.encoding import JsonObject, b64url_encode, sha256
from aauth_lab.core.events import Actor, EventLog, Kind
from aauth_lab.core.httpsig import SignatureErrorCode, SignatureFailure
from aauth_lab.core.ids import (
    AgentId,
    MissionS256,
    Scope,
    ServerId,
    Sub,
    format_scope,
    new_jti,
    parse_scope,
)
from aauth_lab.core.keys import Jwk, Jwks, SigningKey
from aauth_lab.core.server import (
    AgentTokenCall,
    ProblemError,
    deferred,
    install_error_handlers,
    verify_call,
)
from aauth_lab.core.tokens import (
    AuthTokenClaims,
    ClaimsBase,
    Cnf,
    DecodedToken,
    PersonTokenClaims,
    ResourceTokenClaims,
    TokenFormatError,
    decode_token,
    lifetime,
    peek_typ,
    sign_token,
)
from aauth_lab.person_server import pages
from aauth_lab.person_server.state import (
    Approval,
    Mission,
    MissionBlob,
    MissionProposal,
    Pending,
    PendingState,
    PersonServerState,
    TerminationReason,
    TokenRequest,
)
from aauth_lab.person_server.supervisor import (
    AskPerson,
    Deny,
    Grant,
    RuleSupervisor,
    Supervisor,
    TokenRequestContext,
)

PERSON_TOKEN_LIFETIME = 3600  # MUST NOT exceed 1h (§7.1.2)
AUTH_TOKEN_LIFETIME = 3600  # MUST NOT exceed 1h (§9.4.1)
MAX_WAIT_SECONDS = 30


class MissionRequest(BaseModel):
    description: str
    resources: list[str] = []


class PersonTokenRequest(BaseModel):
    resource: str
    mission_s256: MissionS256 | None = None


class AuthTokenRequest(BaseModel):
    resource_token: str
    presented_token: str
    justification: str | None = None
    capabilities: list[str] | None = None


class TokenResponse(BaseModel):
    expires_in: int


class PersonTokenResponse(TokenResponse):
    person_token: str


class AuthTokenResponse(TokenResponse):
    auth_token: str


def _prefer_wait(prefer: str | None) -> float:
    if not prefer:
        return 0.0
    for part in prefer.split(","):
        name, _, value = part.strip().partition("=")
        if name == "wait" and value.isdigit():
            return min(float(value), MAX_WAIT_SECONDS)
    return 0.0


def create_app(topology: Topology, supervisor: Supervisor | None = None) -> FastAPI:
    judge: Supervisor = supervisor or RuleSupervisor()
    me = topology.person_server
    key = SigningKey.generate("ps")
    state = PersonServerState()
    log = EventLog(topology.events_path, Actor.PERSON_SERVER)
    http = httpx.AsyncClient(timeout=10)
    resolver = KeyResolver(http, topology.admits)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await http.aclose()

    app = FastAPI(title="AAuth Lab — Person Server", lifespan=lifespan)
    install_error_handlers(app)

    # ---- helpers -------------------------------------------------------------------

    async def agent_call(request: Request) -> AgentTokenCall:
        call = await verify_call(request, resolver)
        if not isinstance(call.presented, AgentTokenCall):
            # §7: every PS endpoint authenticates callers with an agent token.
            raise SignatureFailure(SignatureErrorCode.INVALID_JWT, "PS requires an agent token")
        return call.presented

    def bind(agent: AgentId) -> str:
        # §13.14: each agent is bound to exactly one person. How the binding is made is
        # out of scope; the lab binds every agent to its single person on first contact.
        if agent not in state.bindings:
            state.bindings[agent] = state.person_name
            log.emit(
                Kind.INFO,
                f"{agent} を {state.person_name} に紐付け（lab の簡略化）",
                spec="§13.14",
            )
        return state.bindings[agent]

    def directed_sub(person: str, resource: ServerId) -> Sub:
        # §14.1: a pairwise identifier per resource.
        return Sub(b64url_encode(sha256(f"{me}|{person}|{resource}".encode()))[:22])

    def mint_person_token(
        agent: AgentId, agent_key: Jwk, agent_exp: int, resource: ServerId, mission: Mission | None
    ) -> tuple[str, PersonTokenClaims]:
        iat, exp = lifetime(PERSON_TOKEN_LIFETIME, cap=agent_exp)
        claims = PersonTokenClaims(
            iss=me,
            jti=new_jti("pt"),
            iat=iat,
            exp=exp,
            aud=resource,
            sub=directed_sub(bind(agent), resource),
            cnf=Cnf(jwk=agent_key),
            mission_s256=mission.s256 if mission else None,
        )
        log.emit(
            Kind.TOKEN,
            f"person token を発行（aud={resource}）",
            {"jti": claims.jti, "sub": claims.sub, "mission_s256": claims.mission_s256},
            spec="§7.1",
        )
        return sign_token(key, claims), claims

    def mint_auth_token(
        rt: ResourceTokenClaims, agent_key: Jwk, scope: Scope, exp_cap: int
    ) -> tuple[str, AuthTokenClaims]:
        iat, exp = lifetime(AUTH_TOKEN_LIFETIME, cap=exp_cap)
        claims = AuthTokenClaims(
            iss=me,
            dwk="aauth-person.json",
            jti=new_jti("auth"),
            iat=iat,
            exp=exp,
            aud=rt.iss,
            ps=me,
            sub=rt.sub,
            cnf=Cnf(jwk=agent_key),
            scope=format_scope(scope),
            mission_s256=rt.mission_s256,
            tenant=rt.tenant,
        )
        log.emit(
            Kind.TOKEN,
            f"auth token を発行（scope={claims.scope}）",
            {
                "jti": claims.jti,
                "aud": claims.aud,
                "scope": claims.scope,
                "exp_in": exp - iat,
                "exp_capped": exp - iat < AUTH_TOKEN_LIFETIME,
            },
            spec="§9.4.1",
        )
        return sign_token(key, claims), claims

    def own_token[C: ClaimsBase](raw: str, claims_type: type[C]) -> DecodedToken[C]:
        """Verify a token this PS issued (person token, or auth token on a step-up)."""
        try:
            decoded = decode_token(raw, claims_type)
        except TokenFormatError as e:
            raise ProblemError(400, "invalid_presented_token", str(e)) from e
        if decoded.claims.iss != me or not decoded.verify_with(key.public_jwk()):
            raise ProblemError(400, "invalid_presented_token", "not issued by this PS")
        if decoded.claims.remaining() <= 0:
            raise ProblemError(400, "expired_presented_token", decoded.claims.jti)
        return decoded

    def active_mission(s256: MissionS256 | None, agent: AgentId) -> Mission | None:
        if s256 is None:
            return None
        mission = state.missions.get(s256)
        if mission is None or mission.blob.agent != agent:
            raise ProblemError(404, "mission_not_found")
        if not mission.active:
            log.emit(
                Kind.REJECT,
                "終了済み mission での要求を拒否",
                {"mission_s256": s256, "termination_reason": mission.terminated},
                spec="§8.8",
            )
            raise ProblemError(
                403,
                "mission_terminated",
                extra={
                    "mission_status": "terminated",
                    "termination_reason": str(mission.terminated),
                },
            )
        return mission

    def interaction_202(pending: Pending, *, status: str = "pending") -> JSONResponse:
        return deferred(
            f"{me}/pending/{pending.id}",
            retry_after=1,
            status=status,
            need=requirement.InteractionRequired(f"{me}/interaction", pending.code),
        )

    # ---- metadata ------------------------------------------------------------------

    @app.get("/.well-known/aauth-person.json")
    def metadata() -> JsonObject:
        return {
            "issuer": me,
            "jwks_uri": f"{me}/.well-known/jwks.json",
            "name": "AAuth Lab Person Server",
            "person_token_endpoint": f"{me}/person",
            "auth_token_endpoint": f"{me}/token",
            "mission_endpoint": f"{me}/mission",
        }

    @app.get("/.well-known/jwks.json")
    def jwks() -> Jwks:
        return Jwks(keys=[key.public_jwk()])

    # ---- mission (§8.1) ------------------------------------------------------------

    @app.post("/mission")
    async def propose_mission(request: Request, body: MissionRequest) -> Response:
        agent = await agent_call(request)
        claims = agent.token.claims
        bind(claims.sub)
        pending = state.add_pending(
            claims.sub,
            claims.cnf.jwk,
            claims.exp,
            MissionProposal(body.description, tuple(ServerId(r) for r in body.resources)),
        )
        log.emit(
            Kind.HOLD,
            "mission の提案を受理。本人の承認待ち",
            {"where": "person_server", "pending": pending.id, "code": pending.code},
            spec="§8.1",
        )
        return interaction_202(pending)

    # ---- person token (§7.1) -------------------------------------------------------

    @app.post("/person")
    async def person_token(request: Request, body: PersonTokenRequest) -> PersonTokenResponse:
        agent = await agent_call(request)
        claims = agent.token.claims
        mission = active_mission(body.mission_s256, claims.sub)
        # Lab policy: the person already approved acting for this agent (via the
        # mission or the binding), so person tokens are issued without asking.
        token, pt = mint_person_token(
            claims.sub, claims.cnf.jwk, claims.exp, ServerId(body.resource), mission
        )
        return PersonTokenResponse(person_token=token, expires_in=pt.exp - pt.iat)

    # ---- auth token (§7.2) ---------------------------------------------------------

    async def verify_resource_token(raw: str, agent_key: Jwk) -> ResourceTokenClaims:
        try:
            rt = (await verify_jwt(raw, ResourceTokenClaims, resolver)).claims
        except JwtVerificationError as e:
            error = (
                "expired_resource_token"
                if e.code is JwtErrorCode.EXPIRED
                else "invalid_resource_token"
            )
            raise ProblemError(400, error, e.detail) from e
        if rt.aud != me or rt.ps != me:
            raise ProblemError(400, "invalid_resource_token", "aud/ps does not name this PS")
        if rt.agent_jkt != agent_key.thumbprint():
            raise ProblemError(400, "invalid_resource_token", "agent_jkt is not the signer")
        return rt

    def verify_presented(raw: str, rt: ResourceTokenClaims) -> tuple[bool, int]:
        """§6.7.2 step 3. Returns (is_step_up, presented exp)."""
        try:
            typ = peek_typ(raw)
        except TokenFormatError as e:
            raise ProblemError(400, "invalid_presented_token", str(e)) from e
        presented: DecodedToken[PersonTokenClaims] | DecodedToken[AuthTokenClaims]
        if typ == "aa-person+jwt":
            presented = own_token(raw, PersonTokenClaims)
        elif typ == "aa-auth+jwt":
            presented = own_token(raw, AuthTokenClaims)
        else:
            raise ProblemError(400, "invalid_presented_token", f"typ {typ!r}")
        p = presented.claims
        if p.aud != rt.iss or p.cnf.jwk.thumbprint() != rt.agent_jkt:
            raise ProblemError(400, "invalid_presented_token", "aud or cnf mismatch")
        if (p.jti, p.sub, p.mission_s256, p.tenant) != (
            rt.presented_jti,
            rt.sub,
            rt.mission_s256,
            rt.tenant,
        ):
            # Appendix C.1.9: this is how mission stripping is detected.
            raise ProblemError(400, "invalid_resource_token", "does not match presented token")
        return isinstance(p, AuthTokenClaims), p.exp

    @app.post("/token")
    async def auth_token(request: Request, body: AuthTokenRequest) -> Response:
        agent = await agent_call(request)
        claims = agent.token.claims
        bind(claims.sub)
        rt = await verify_resource_token(body.resource_token, claims.cnf.jwk)
        step_up, presented_exp = verify_presented(body.presented_token, rt)
        mission = active_mission(rt.mission_s256, claims.sub)

        try:
            resource_meta = await resolver.metadata(rt.iss, "aauth-resource.json")
        except DiscoveryError as e:
            raise ProblemError(400, "invalid_resource_token", str(e)) from e
        raw_descriptions = resource_meta.get("scope_descriptions")
        descriptions = (
            {k: v for k, v in raw_descriptions.items() if isinstance(v, str)}
            if isinstance(raw_descriptions, dict)
            else {}
        )
        requested = parse_scope(rt.scope)
        if not requested <= descriptions.keys():
            raise ProblemError(400, "invalid_resource_token", "scope not published by resource")

        exp_cap = min(claims.exp, presented_exp)
        verdict = judge.evaluate(
            TokenRequestContext(
                agent=claims.sub,
                resource=rt.iss,
                requested=requested,
                already_consented=mission.consents.get(rt.iss, frozenset())
                if mission
                else frozenset(),
                mission=mission,
                justification=body.justification,
                step_up=step_up,
            )
        )
        decision_detail: JsonObject = {
            "requested": format_scope(requested),
            "step_up": step_up,
            "justification": body.justification,
        }
        match verdict:
            case Grant(scope=scope, reason=reason):
                log.emit(
                    Kind.DECISION, f"Supervisor: 許可 — {reason}", decision_detail, spec="§4.4"
                )
                token, at = mint_auth_token(rt, claims.cnf.jwk, scope, exp_cap)
                return JSONResponse(
                    AuthTokenResponse(auth_token=token, expires_in=at.exp - at.iat).model_dump()
                )
            case Deny(reason=reason):
                log.emit(
                    Kind.DECISION, f"Supervisor: 拒否 — {reason}", decision_detail, spec="§4.4"
                )
                raise ProblemError(403, "denied", reason)
            case AskPerson(scope=scope, reason=reason):
                log.emit(
                    Kind.DECISION,
                    f"Supervisor: 本人に確認 — {reason}",
                    decision_detail,
                    spec="§4.4",
                )
                if "interaction" not in (body.capabilities or []):
                    raise ProblemError(403, "user_unreachable", "agent cannot reach the person")
                pending = state.add_pending(
                    claims.sub,
                    claims.cnf.jwk,
                    claims.exp,
                    TokenRequest(
                        resource_token=rt,
                        requested=scope,
                        justification=body.justification,
                        supervisor_reason=reason,
                        exp_cap=exp_cap,
                        step_up=step_up,
                        resource_name=str(resource_meta.get("name") or rt.iss),
                        scope_descriptions=descriptions,
                    ),
                )
                log.emit(
                    Kind.HOLD,
                    "token 要求を保留。本人の判断待ち",
                    {"where": "person_server", "pending": pending.id, "code": pending.code},
                    spec="§7.2.2",
                )
                return interaction_202(pending)

    # ---- pending URL (§11.8) -------------------------------------------------------

    @app.get("/pending/{pending_id}")
    async def poll(
        request: Request,
        pending_id: str,
        prefer: Annotated[str | None, Header()] = None,
    ) -> Response:
        agent = await agent_call(request)
        pending = state.pendings.get(pending_id)
        # §13.2: verify the agent's identity on every poll.
        if pending is None or pending.agent != agent.token.claims.sub:
            raise ProblemError(404, "not_found")
        wait = _prefer_wait(prefer)
        if wait and pending.state in (PendingState.PENDING, PendingState.INTERACTING):
            pending.changed.clear()
            with suppress(TimeoutError):
                await asyncio.wait_for(pending.changed.wait(), timeout=wait)
        pending.refresh_expiry()
        match pending.state:
            case PendingState.PENDING | PendingState.INTERACTING:
                return interaction_202(pending, status=pending.state.value)
            case PendingState.APPROVED:
                assert pending.result is not None
                pending.settle(PendingState.GONE)
                return JSONResponse(pending.result)
            case PendingState.DENIED:
                pending.settle(PendingState.GONE)
                raise ProblemError(403, "denied", "The person declined the request.")
            case PendingState.EXPIRED:
                pending.settle(PendingState.GONE)
                raise ProblemError(408, "expired")
            case PendingState.GONE:
                raise ProblemError(410, "gone")

    # ---- the person's surfaces -----------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> str:
        return pages.dashboard(
            state.person_name, state.open_requests(), list(state.missions.values())
        )

    @app.get("/interaction", response_class=HTMLResponse)
    async def interaction(code: Annotated[str | None, Query()] = None) -> str:
        # §13.13: approvals need an authenticated person. The lab PS is loopback-only,
        # which the spec exempts; a real PS would require a login here.
        if code is None:
            return pages.code_entry_page()
        pending = state.redeem_code(code)
        if pending is None:
            return pages.code_entry_page("コードが無効か、すでに使用済みです（invalid_code）")
        pending.refresh_expiry()
        if pending.state is not PendingState.PENDING:
            return pages.code_entry_page(f"この要求は {pending.state} です")
        pending.settle(PendingState.INTERACTING)
        log.emit(
            Kind.INFO,
            "本人が確認画面を開いた",
            {"pending": pending.id},
            actor=Actor.PERSON,
            spec="§11.8.2",
        )
        return pages.consent_page(pending, state.person_name)

    @app.post("/interaction/{pending_id}/decision", response_class=HTMLResponse)
    async def decide(
        pending_id: str,
        decision: Annotated[str, Form()],
        nonce: Annotated[str, Form()],
        scope: Annotated[list[str] | None, Form()] = None,
    ) -> str:
        pending = state.pendings.get(pending_id)
        if pending is None or pending.decision_nonce != nonce:
            raise ProblemError(400, "invalid_request")
        if pending.state is not PendingState.INTERACTING:
            return pages.code_entry_page(f"この要求は {pending.state} です")
        chosen = frozenset(scope or [])
        if decision == "approve":
            apply_approval(pending, chosen)
            return pages.done_page(approved=True)
        log.emit(Kind.DECISION, "本人: 拒否", {"pending": pending.id}, actor=Actor.PERSON)
        pending.settle(PendingState.DENIED)
        return pages.done_page(approved=False)

    def apply_approval(pending: Pending, chosen: Scope) -> None:
        match pending.subject:
            case MissionProposal(description=description, resources=resources):
                mission = Mission.approve(
                    MissionBlob(
                        agent=pending.agent,
                        approved_at=datetime.now(UTC).isoformat(timespec="seconds"),
                        description=description,
                        approved_resources=list(resources),
                    )
                )
                state.missions[mission.s256] = mission
                log.emit(
                    Kind.DECISION,
                    "本人: mission を承認",
                    {"mission_s256": mission.s256},
                    actor=Actor.PERSON,
                    spec="§8.2",
                )
                person_tokens: JsonObject = {
                    r: mint_person_token(
                        pending.agent, pending.agent_key, pending.agent_token_exp, r, mission
                    )[0]
                    for r in resources
                }
                pending.result = {
                    "s256": mission.s256,
                    "mission": b64url_encode(mission.raw),
                    "capabilities": ["interaction"],
                    "person_tokens": person_tokens,
                }
            case TokenRequest() as request:
                granted = chosen & request.requested
                if not granted:
                    log.emit(Kind.DECISION, "本人: scope を全て外した → 拒否", actor=Actor.PERSON)
                    pending.settle(PendingState.DENIED)
                    return
                narrowed = granted != request.requested
                log.emit(
                    Kind.DECISION,
                    f"本人: 承認（scope={format_scope(granted)}）"
                    + ("— 要求より縮小" if narrowed else ""),
                    {
                        "granted": format_scope(granted),
                        "requested": format_scope(request.requested),
                    },
                    actor=Actor.PERSON,
                    spec="§11.10",
                )
                rt = request.resource_token
                if rt.mission_s256 and (under := state.missions.get(rt.mission_s256)):
                    under.consents[rt.iss] = under.consents.get(rt.iss, frozenset()) | granted
                    under.log.append({"ts": time.time(), "consented": format_scope(granted)})
                token, at = mint_auth_token(rt, pending.agent_key, granted, request.exp_cap)
                pending.result = {"auth_token": token, "expires_in": at.exp - at.iat}
        pending.approval = Approval(chosen)
        pending.settle(PendingState.APPROVED)

    @app.post("/lab/missions/{s256}/revoke")
    async def revoke_mission(s256: MissionS256) -> RedirectResponse:
        """Stand-in for the mission control endpoint (§8.6, companion spec TBD)."""
        mission = state.missions.get(s256)
        if mission is not None and mission.active:
            mission.terminated = TerminationReason.REVOKED
            log.emit(
                Kind.DECISION,
                "本人: mission を終了（revoked）",
                {"mission_s256": s256},
                actor=Actor.PERSON,
                spec="§8.6",
            )
        return RedirectResponse("/", status_code=303)

    return app
