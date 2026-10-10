"""Resource (§6): a document API. It decides what is required and enforces it (§4.4).

Two step-up deliveries are implemented side by side (§6.5.1):

* RETRY    — 401. The resource keeps nothing; the agent holds the intent and resends.
* DEFERRED — 202. The resource holds the invocation and runs it on the first poll
             that presents a sufficient auth token, then answers replays from the
             stored result instead of running it again.
"""

import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from aauth_lab.config import StepUpDelivery, Topology
from aauth_lab.core import requirement
from aauth_lab.core.discovery import KeyResolver
from aauth_lab.core.encoding import JsonObject
from aauth_lab.core.events import Actor, EventLog, Kind
from aauth_lab.core.ids import Jti, MissionS256, Scope, ServerId, Sub, format_scope, new_jti
from aauth_lab.core.keys import Jwks, JwkThumbprint, SigningKey
from aauth_lab.core.server import (
    AgentTokenCall,
    AuthTokenCall,
    PersonTokenCall,
    ProblemError,
    VerifiedCall,
    challenge,
    deferred,
    install_error_handlers,
    verify_call,
)
from aauth_lab.core.tokens import ResourceTokenClaims, lifetime, sign_token

RESOURCE_TOKEN_LIFETIME = 300  # SHOULD NOT exceed 5 minutes (§6.7.1)
HOLD_LIFETIME = 600

SCOPE_DESCRIPTIONS = {
    "docs.read": "あなたの文書の一覧と内容を読む",
    "docs.write": "文書を作成・更新する",
    "docs.delete": "文書を完全に削除する（元に戻せません）",
    "docs.admin": "共有設定・権限を変更する",
}


@dataclass
class Document:
    id: int
    title: str
    body: str
    protected: bool = False
    """Resource-side business rule: no token, however broad, deletes a protected doc."""


def _seed() -> dict[int, Document]:
    docs = [
        Document(1, "2026年度 事業計画", "…"),
        Document(2, "議事録 2026-09-01", "…"),
        Document(3, "古い下書き (2019)", "…"),
        Document(4, "雇用契約書", "…", protected=True),
    ]
    return {d.id: d for d in docs}


@dataclass(frozen=True)
class Authorized:
    sub: Sub
    scope: Scope
    jti: Jti


@dataclass(frozen=True)
class StoredResult:
    status: int
    body: JsonObject


@dataclass
class HeldInvocation:
    """An invocation the resource is holding while authorization is obtained (§6.5.1)."""

    id: str
    method: str
    path: str
    doc_id: int
    needed: Scope
    agent_jkt: JwkThumbprint
    ps: ServerId
    sub: Sub
    mission_s256: MissionS256 | None
    current_scope: Scope
    presented_jti: Jti
    resource_token: str
    resource_token_exp: int
    expires_at: float
    executed_with: Jti | None = None
    results: dict[Jti, StoredResult] = field(default_factory=dict)
    """Keyed by auth token jti; kept so a lost response can be re-fetched, not re-run."""


class LabSettings(BaseModel):
    step_up_delivery: StepUpDelivery


class DocSummary(BaseModel):
    id: int
    title: str
    protected: bool


def create_app(topology: Topology) -> FastAPI:
    me = topology.resource
    key = SigningKey.generate("rs")
    log = EventLog(topology.events_path, Actor.RESOURCE)
    http = httpx.AsyncClient(timeout=10)
    resolver = KeyResolver(http, topology.admits)
    docs = _seed()
    held: dict[str, HeldInvocation] = {}
    settings = LabSettings(step_up_delivery=topology.step_up_delivery)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await http.aclose()

    # /docs is the document API, so move Swagger UI out of its way.
    app = FastAPI(
        title="AAuth Lab — Resource (Docs)",
        lifespan=lifespan,
        docs_url="/_swagger",
        redoc_url=None,
    )
    install_error_handlers(app)

    # ---- issuing resource tokens (§6.7) --------------------------------------------

    def resource_token(
        *,
        ps: ServerId,
        sub: Sub,
        presented_jti: Jti,
        agent_jkt: JwkThumbprint,
        scope: Scope,
        mission_s256: MissionS256 | None,
    ) -> tuple[str, ResourceTokenClaims]:
        iat, exp = lifetime(RESOURCE_TOKEN_LIFETIME)
        claims = ResourceTokenClaims(
            iss=me,
            jti=new_jti("rt"),
            iat=iat,
            exp=exp,
            aud=ps,  # three-party: the PS that issued the presented token
            ps=ps,
            sub=sub,
            presented_jti=presented_jti,
            agent_jkt=agent_jkt,
            scope=format_scope(scope),
            mission_s256=mission_s256,
        )
        return sign_token(key, claims), claims

    # ---- the enforcement point -----------------------------------------------------

    def authorize(
        call: VerifiedCall, needed: Scope, delivery: StepUpDelivery, *, doc_id: int | None = None
    ) -> Authorized | Response:
        """Decide what this request still needs. Returns Authorized, or the response to send."""
        jkt = call.key.thumbprint()
        what = f"{call.parts.method} {call.parts.path}"
        match call.presented:
            case AgentTokenCall(token=t):
                if t.claims.ps is None:
                    raise ProblemError(403, "forbidden", "this resource needs a person server")
                log.emit(
                    Kind.CHALLENGE,
                    f"{what}: 誰の代理か不明 → person token を要求",
                    {"status": 401},
                    spec="§6.4",
                )
                return challenge(requirement.PersonTokenRequired())

            case PersonTokenCall(token=t):
                p = t.claims
                if p.aud != me:
                    raise ProblemError(
                        401, "invalid_token", "person token aud is not this resource"
                    )
                raw, rt = resource_token(
                    ps=p.iss,
                    sub=p.sub,
                    presented_jti=p.jti,
                    agent_jkt=jkt,
                    scope=needed,
                    mission_s256=p.mission_s256,
                )
                return auth_token_challenge(
                    call, raw, rt, needed, frozenset(), delivery, doc_id, step_up=False
                )

            case AuthTokenCall(token=t):
                a = t.claims
                if a.aud != me or a.ps != a.iss:
                    raise ProblemError(401, "invalid_token", "auth token not for this resource")
                granted = frozenset((a.scope or "").split())
                if needed <= granted:
                    return Authorized(a.sub, granted, a.jti)
                # §6.5: step-up — the request needs more than the token provides.
                raw, rt = resource_token(
                    ps=a.ps,
                    sub=a.sub,
                    presented_jti=a.jti,
                    agent_jkt=jkt,
                    scope=granted | needed,
                    mission_s256=a.mission_s256,
                )
                return auth_token_challenge(
                    call, raw, rt, needed, granted, delivery, doc_id, step_up=True
                )

    def auth_token_challenge(
        call: VerifiedCall,
        raw: str,
        rt: ResourceTokenClaims,
        needed: Scope,
        current: Scope,
        delivery: StepUpDelivery,
        doc_id: int | None,
        *,
        step_up: bool,
    ) -> Response:
        what = f"{call.parts.method} {call.parts.path}"
        label = "step-up" if step_up else "初回"
        detail: JsonObject = {
            "needed": format_scope(needed),
            "held": format_scope(current),
            "resource_token_scope": rt.scope,
            "presented_jti": rt.presented_jti,
            "delivery": delivery.value,
        }
        need = requirement.AuthTokenRequired(raw)
        if delivery is StepUpDelivery.RETRY or doc_id is None:
            log.emit(
                Kind.CHALLENGE,
                f"{what}: {label} — {format_scope(needed - current)} が足りない → 401 auth-token",
                {**detail, "status": 401},
                spec="§6.5",
            )
            log.emit(
                Kind.HOLD,
                f"{what} は実行せず破棄（resource は何も保持しない。再送するかは agent 次第）",
                {"where": "agent"},
                spec="§6.5.1",
            )
            return challenge(need)

        invocation = HeldInvocation(
            id=secrets.token_urlsafe(18),
            method=call.parts.method,
            path=call.parts.path,
            doc_id=doc_id,
            needed=needed,
            agent_jkt=call.key.thumbprint(),
            ps=rt.ps,
            sub=rt.sub,
            mission_s256=rt.mission_s256,
            current_scope=current,
            presented_jti=rt.presented_jti,
            resource_token=raw,
            resource_token_exp=rt.exp,
            expires_at=time.time() + HOLD_LIFETIME,
        )
        held[invocation.id] = invocation
        log.emit(
            Kind.CHALLENGE,
            f"{what}: {label} — {format_scope(needed - current)} が足りない → 202 auth-token",
            {**detail, "status": 202},
            spec="§6.5.1",
        )
        log.emit(
            Kind.HOLD,
            f"{what} を resource が保留（auth token 付きの poll で実行する）",
            {"where": "resource", "pending": invocation.id},
            spec="§6.5.1",
        )
        return deferred(f"{me}/pending/{invocation.id}", retry_after=2, need=need)

    # ---- the API -------------------------------------------------------------------

    def summary(d: Document) -> DocSummary:
        return DocSummary(id=d.id, title=d.title, protected=d.protected)

    @app.get("/docs", response_model=None)
    async def list_docs(request: Request) -> list[DocSummary] | Response:
        call = await verify_call(request, resolver)
        # A read can always be resent safely, so it is challenged with a plain 401.
        result = authorize(call, frozenset({"docs.read"}), StepUpDelivery.RETRY)
        if not isinstance(result, Authorized):
            return result
        log.emit(Kind.EXECUTE, f"GET /docs を実行（{len(docs)} 件）", spec="§4.4")
        return [summary(d) for d in docs.values()]

    def delete_doc(doc_id: int, via: Literal["direct", "held"]) -> StoredResult:
        doc = docs.get(doc_id)
        if doc is None:
            return StoredResult(404, {"error": "not_found"})
        if doc.protected:
            # Authorization said "this agent may delete documents"; the resource's own
            # rule still says "not this one". The token is necessary, not sufficient.
            log.emit(
                Kind.REJECT,
                f"「{doc.title}」は保護対象。auth token があっても削除しない",
                {"doc": doc_id},
                spec="§4.4",
            )
            return StoredResult(403, {"error": "protected", "detail": f"{doc.title} is protected"})
        del docs[doc_id]
        log.emit(
            Kind.EXECUTE,
            f"「{doc.title}」を削除"
            + ("（保留していた invocation を実行）" if via == "held" else ""),
            {"doc": doc_id},
            spec="§6.5.1" if via == "held" else "§4.4",
        )
        return StoredResult(200, {"deleted": doc_id, "title": doc.title})

    @app.delete("/docs/{doc_id}", response_model=None)
    async def delete(request: Request, doc_id: int) -> Response:
        call = await verify_call(request, resolver)
        result = authorize(
            call, frozenset({"docs.delete"}), settings.step_up_delivery, doc_id=doc_id
        )
        if not isinstance(result, Authorized):
            return result
        stored = delete_doc(doc_id, "direct")
        return JSONResponse(stored.body, status_code=stored.status)

    # ---- pending URL for held invocations (§6.5.1, §11.8) --------------------------

    @app.get("/pending/{pending_id}", response_model=None)
    async def poll(request: Request, pending_id: str) -> Response:
        call = await verify_call(request, resolver)
        invocation = held.get(pending_id)
        # §13.2: verify the agent on every poll — here, the same key that was challenged.
        if invocation is None or invocation.agent_jkt != call.key.thumbprint():
            raise ProblemError(404, "not_found")

        if isinstance(call.presented, AuthTokenCall):
            a = call.presented.token.claims
            if a.aud != me or a.sub != invocation.sub:
                raise ProblemError(401, "invalid_token", "auth token does not match the hold")
            replay = invocation.results.get(a.jti)
            if replay is not None:
                log.emit(
                    Kind.INFO,
                    "同じ auth token で再 poll → 保存済みの結果を返す（再実行しない）",
                    {"jti": a.jti, "status": replay.status},
                    spec="§6.5.1",
                )
                return JSONResponse(replay.body, status_code=replay.status)
            if invocation.executed_with is not None:
                raise ProblemError(410, "gone", "already completed with another auth token")
            granted = frozenset((a.scope or "").split())
            if not invocation.needed <= granted:
                # The person narrowed the grant (§11.10). The spec does not say what a
                # holding resource does then; the lab ends the hold with 403.
                log.emit(
                    Kind.REJECT,
                    f"auth token の scope（{format_scope(granted)}）では足りない → 保留を終了",
                    {"needed": format_scope(invocation.needed)},
                )
                invocation.executed_with = a.jti
                stored = StoredResult(403, {"error": "insufficient_scope"})
                invocation.results[a.jti] = stored
                return JSONResponse(stored.body, status_code=stored.status)
            log.emit(
                Kind.RESUME,
                f"auth token 付きの poll を受信 → 保留していた {invocation.method} {invocation.path} を再開",
                {"jti": a.jti, "scope": a.scope},
                spec="§6.5.1",
            )
            invocation.executed_with = a.jti
            stored = delete_doc(invocation.doc_id, "held")
            invocation.results[a.jti] = stored
            return JSONResponse(stored.body, status_code=stored.status)

        if time.time() > invocation.expires_at:
            log.emit(Kind.REJECT, "保留の期限切れ", {"pending": pending_id}, spec="§11.8.4")
            raise ProblemError(408, "expired")
        if invocation.resource_token_exp <= time.time():
            # §6.5.1: MAY include a fresh resource token on a later poll.
            raw, rt = resource_token(
                ps=invocation.ps,
                sub=invocation.sub,
                presented_jti=invocation.presented_jti,
                agent_jkt=invocation.agent_jkt,
                scope=invocation.current_scope | invocation.needed,
                mission_s256=invocation.mission_s256,
            )
            invocation.resource_token, invocation.resource_token_exp = raw, rt.exp
        return deferred(
            f"{me}/pending/{pending_id}",
            retry_after=2,
            need=requirement.AuthTokenRequired(invocation.resource_token),
        )

    # ---- metadata and lab controls -------------------------------------------------

    @app.get("/.well-known/aauth-resource.json")
    def metadata() -> JsonObject:
        return {
            "issuer": me,
            "jwks_uri": f"{me}/.well-known/jwks.json",
            "access_mode": "auth-token",
            "name": "Lab Docs",
            "description": "あなたの文書を保管する API（AAuth Lab）",
            "scope_descriptions": dict(SCOPE_DESCRIPTIONS),
        }

    @app.get("/.well-known/jwks.json")
    def jwks() -> Jwks:
        return Jwks(keys=[key.public_jwk()])

    @app.get("/lab/settings")
    async def get_settings() -> LabSettings:
        return settings

    @app.put("/lab/settings")
    async def put_settings(new: LabSettings) -> LabSettings:
        settings.step_up_delivery = new.step_up_delivery
        log.emit(Kind.INFO, f"step-up の返し方を {new.step_up_delivery} に変更（lab 設定）")
        return settings

    @app.get("/lab/docs")
    async def lab_docs() -> list[DocSummary]:
        return [summary(d) for d in docs.values()]

    @app.post("/lab/reset")
    async def lab_reset() -> list[DocSummary]:
        docs.clear()
        docs.update(_seed())
        held.clear()
        return [summary(d) for d in docs.values()]

    return app
