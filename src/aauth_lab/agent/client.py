"""The agent: an HTTP client that signs every request and reacts to AAuth-Requirement.

The agent never decides whether it is *allowed* to do something at a resource — it
only carries tokens between the parties that decide (PS, person) and the party that
enforces (resource). What it does decide is whether to *retry* after a 401.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, ValidationError

from aauth_lab.core import httpsig, requirement
from aauth_lab.core.discovery import JwtVerificationError, KeyResolver, verify_jwt
from aauth_lab.core.encoding import (
    JsonObject,
    JsonValue,
    b64url_decode,
    b64url_encode,
    parse_json_value,
    sha256,
)
from aauth_lab.core.events import Actor, EventLog, Kind
from aauth_lab.core.ids import MissionS256, ServerId, format_scope, parse_scope
from aauth_lab.core.keys import SigningKey
from aauth_lab.core.tokens import (
    AgentTokenClaims,
    AuthTokenClaims,
    PersonTokenClaims,
    ResourceTokenClaims,
    decode_token,
    peek_typ,
)

MAX_STEPS = 8
POLL_WAIT_SECONDS = 20


@dataclass(frozen=True)
class InteractionPrompt:
    """What the agent must get in front of the person (§11.6.3.2 "display code")."""

    url: str
    code: str
    reason: str

    @property
    def link(self) -> str:
        return f"{self.url}?code={self.code}"


type InteractionHandler = Callable[[InteractionPrompt], Awaitable[None]]


@dataclass(frozen=True)
class Done:
    status: int
    body: JsonValue


@dataclass(frozen=True)
class Refused:
    """The request ended without being served. ``by`` is the party that said no."""

    by: Actor
    error: str
    detail: str | None = None


type Outcome = Done | Refused


class AAuthError(Exception):
    def __init__(self, refused: Refused) -> None:
        super().__init__(f"{refused.by}: {refused.error} {refused.detail or ''}")
        self.refused = refused


class _TokenBody(BaseModel):
    auth_token: str | None = None
    person_token: str | None = None


class _MissionBody(BaseModel):
    s256: MissionS256
    mission: str
    person_tokens: dict[str, str] = {}


class _Problem(BaseModel):
    error: str = "unknown"
    detail: str | None = None


def _origin(url: str) -> ServerId:
    u = httpx.URL(url)
    port = f":{u.port}" if u.port else ""
    return ServerId(f"{u.scheme}://{u.host}{port}")


def _problem(response: httpx.Response) -> _Problem:
    try:
        return _Problem.model_validate_json(response.content)
    except ValidationError:
        return _Problem(error=f"http_{response.status_code}")


def _describe(token: str) -> str:
    return {
        "aa-agent+jwt": "agent token",
        "aa-person+jwt": "person token",
        "aa-auth+jwt": "auth token",
    }.get(peek_typ(token), "?")


@dataclass
class Agent:
    key: SigningKey
    agent_token: str
    http: httpx.AsyncClient
    resolver: KeyResolver
    log: EventLog
    on_interaction: InteractionHandler
    mission_s256: MissionS256 | None = None
    person_tokens: dict[ServerId, str] = field(default_factory=dict)
    auth_tokens: dict[ServerId, str] = field(default_factory=dict)
    last_hold: str | None = None
    """Pending URL of the most recent invocation a resource held for us."""

    @property
    def claims(self) -> AgentTokenClaims:
        return decode_token(self.agent_token, AgentTokenClaims).claims

    @property
    def ps(self) -> ServerId:
        ps = self.claims.ps
        if ps is None:
            raise RuntimeError("this agent has no person server")
        return ps

    # ---- signing -------------------------------------------------------------------

    async def signed(
        self,
        method: str,
        url: str,
        token: str,
        body: JsonObject | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Send ``method url`` signed with our key, presenting ``token`` in Signature-Key."""
        u = httpx.URL(url)
        content = b"" if body is None else httpx.Request("POST", url, json=body).content
        h = {"signature-key": httpsig.signature_key_header(token), **(headers or {})}
        if content:
            h["content-type"] = "application/json"
            h["content-digest"] = httpsig.content_digest(content)
        authority = u.host + (f":{u.port}" if u.port else "")
        parts = httpsig.RequestParts(
            method, authority, u.raw_path.decode().split("?")[0], h, content
        )
        h.update(httpsig.sign(parts, self.key))
        return await self.http.request(method, url, content=content or None, headers=h)

    # ---- mission (§8.1) ------------------------------------------------------------

    async def propose_mission(self, description: str, resources: list[ServerId]) -> MissionS256:
        self.log.emit(
            Kind.REQUEST,
            "mission を提案",
            {"description": description, "resources": list(resources)},
            spec="§8.1",
        )
        response = await self.signed(
            "POST",
            f"{self.ps}/mission",
            self.agent_token,
            {"description": description, "resources": list(resources)},
        )
        response = await self._settle_at_ps(response, "mission の承認")
        if response.status_code != 200:
            raise AAuthError(Refused(Actor.PERSON_SERVER, _problem(response).error))
        body = _MissionBody.model_validate_json(response.content)
        # §8.2: SHOULD verify s256 against the decoded bytes before first use.
        if b64url_encode(sha256(b64url_decode(body.mission))) != body.s256:
            raise AAuthError(Refused(Actor.PERSON_SERVER, "mission_digest_mismatch"))
        self.mission_s256 = body.s256
        for resource, token in body.person_tokens.items():
            self.person_tokens[ServerId(resource)] = token
        self.log.emit(
            Kind.INFO,
            "mission 承認を確認（s256 を検証）",
            {"mission_s256": body.s256, "person_tokens_for": list(body.person_tokens)},
            spec="§8.2",
        )
        return body.s256

    # ---- calling a resource (§6) ---------------------------------------------------

    async def call(self, method: str, url: str, *, justification: str | None = None) -> Outcome:
        try:
            return await self._call(method, url, justification)
        except AAuthError as e:
            if e.refused.by is Actor.PERSON_SERVER and self.last_hold:
                self.log.emit(
                    Kind.INFO,
                    "PS で拒否されたが、resource はそれを知らない。保留は期限切れまで残る",
                    {"location": self.last_hold},
                    spec="§11.8",
                )
            return e.refused

    async def _call(self, method: str, url: str, justification: str | None) -> Outcome:
        self.last_hold = None
        resource = _origin(url)
        token = (
            self.auth_tokens.get(resource) or self.person_tokens.get(resource) or self.agent_token
        )
        for _ in range(MAX_STEPS):
            self.log.emit(
                Kind.REQUEST, f"{method} {url}", {"presenting": _describe(token)}, spec="§11.3"
            )
            response = await self.signed(method, url, token)
            raw_need = response.headers.get(requirement.HEADER)
            need = requirement.parse(raw_need) if raw_need else None

            match response.status_code, need:
                case 401, requirement.PersonTokenRequired():
                    token = await self._person_token(resource)
                case 401, requirement.AuthTokenRequired(resource_token=rt):
                    token = await self._auth_token(resource, rt, token, justification)
                    self.log.emit(
                        Kind.RESUME,
                        f"auth token を得たので {method} を再送する（再送するかは agent の判断）",
                        {"where": "agent"},
                        spec="§6.5",
                    )
                case 202, requirement.AuthTokenRequired(resource_token=rt):
                    location = response.headers["location"]
                    self.last_hold = location
                    self.log.emit(
                        Kind.HOLD,
                        f"{method} は resource 側で保留中。auth token を取りに行く",
                        {"where": "resource", "location": location},
                        spec="§6.5.1",
                    )
                    token = await self._auth_token(resource, rt, token, justification)
                    return await self._poll_resource(location, token)
                case 202, _:
                    return Refused(Actor.RESOURCE, "unsupported_requirement", raw_need)
                case 401, requirement.UnknownRequirement(value=v):
                    return Refused(Actor.RESOURCE, "unsupported_requirement", v)
                case 401, None:
                    return Refused(
                        Actor.RESOURCE, "signature_error", response.headers.get("signature-error")
                    )
                case status, _:
                    return self._finish(status, response)
        return Refused(Actor.AGENT, "too_many_steps")

    def _finish(self, status: int, response: httpx.Response) -> Outcome:
        body = parse_json_value(response.content) if response.content else None
        if status < 400:
            return Done(status, body)
        problem = _problem(response)
        return Refused(Actor.RESOURCE, problem.error, problem.detail)

    async def _poll_resource(self, location: str, auth_token: str) -> Outcome:
        self.log.emit(
            Kind.REQUEST,
            "auth token を付けて resource の pending URL を poll",
            {"location": location},
            spec="§6.5.1",
        )
        for _ in range(MAX_STEPS):
            response = await self.signed("GET", location, auth_token)
            if response.status_code != 202:
                return self._finish(response.status_code, response)
            await asyncio.sleep(float(response.headers.get("retry-after", "5")))
        return Refused(Actor.AGENT, "too_many_polls")

    async def repoll(self, location: str, resource: ServerId) -> Outcome:
        """Poll a held invocation again with the auth token we hold (lost-response check)."""
        return await self._poll_resource(location, self.auth_tokens[resource])

    # ---- obtaining tokens from the PS (§7.1, §7.2) ---------------------------------

    async def _person_token(self, resource: ServerId) -> str:
        body: JsonObject = {"resource": resource}
        if self.mission_s256:
            body["mission_s256"] = self.mission_s256
        self.log.emit(
            Kind.REQUEST, "PS に person token を要求", {"resource": resource}, spec="§7.1"
        )
        response = await self.signed("POST", f"{self.ps}/person", self.agent_token, body)
        if response.status_code != 200:
            p = _problem(response)
            raise AAuthError(Refused(Actor.PERSON_SERVER, p.error, p.detail))
        token = _TokenBody.model_validate_json(response.content).person_token
        assert token is not None
        self.person_tokens[resource] = token
        return token

    async def _verify_resource_token(
        self, raw: str, resource: ServerId, presented: str
    ) -> ResourceTokenClaims:
        """§6.7.3 — the agent checks the challenge before carrying it to its PS."""
        try:
            rt = (await verify_jwt(raw, ResourceTokenClaims, self.resolver)).claims
        except JwtVerificationError as e:
            raise AAuthError(Refused(Actor.AGENT, "invalid_resource_token", e.detail)) from e
        p = (
            decode_token(presented, PersonTokenClaims).claims
            if peek_typ(presented) == "aa-person+jwt"
            else decode_token(presented, AuthTokenClaims).claims
        )
        checks = {
            "iss is the resource we called": rt.iss == resource,
            "agent_jkt is our key": rt.agent_jkt == self.key.public_jwk().thumbprint(),
            "ps is our PS": rt.ps == self.ps,
            "sub/presented_jti match what we presented": (rt.sub, rt.presented_jti)
            == (p.sub, p.jti),
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise AAuthError(Refused(Actor.AGENT, "invalid_resource_token", ", ".join(failed)))
        return rt

    async def _auth_token(
        self, resource: ServerId, rt_raw: str, presented: str, justification: str | None
    ) -> str:
        rt = await self._verify_resource_token(rt_raw, resource, presented)
        self.log.emit(
            Kind.REQUEST,
            f"resource token を PS に持っていく（scope={rt.scope}）",
            {"presented": _describe(presented), "justification": justification},
            spec="§7.2",
        )
        body: JsonObject = {
            "resource_token": rt_raw,
            "presented_token": presented,
            "capabilities": ["interaction"],
        }
        if justification:
            body["justification"] = justification
        response = await self.signed(
            "POST", f"{self.ps}/token", self.agent_token, body, {"prefer": "wait=5"}
        )
        response = await self._settle_at_ps(response, f"{format_scope(parse_scope(rt.scope))}")
        if response.status_code != 200:
            p = _problem(response)
            raise AAuthError(Refused(Actor.PERSON_SERVER, p.error, p.detail))
        token = _TokenBody.model_validate_json(response.content).auth_token
        assert token is not None
        at = decode_token(token, AuthTokenClaims).claims
        # §9.4.4 (subset): the token is ours and for this resource.
        if at.aud != resource or not at.cnf.jwk.same_key(self.key.public_jwk()):
            raise AAuthError(Refused(Actor.AGENT, "invalid_auth_token"))
        self.auth_tokens[resource] = token
        self.log.emit(
            Kind.INFO,
            f"auth token を受領（scope={at.scope}, 残り {int(at.remaining())} 秒）",
            {"jti": at.jti},
            spec="§9.4.4",
        )
        return token

    async def _settle_at_ps(self, response: httpx.Response, what: str) -> httpx.Response:
        """Follow a PS deferred response to a terminal one (§11.8.4)."""
        if response.status_code != 202:
            return response
        raw_need = response.headers.get(requirement.HEADER)
        need = requirement.parse(raw_need) if raw_need else None
        location = response.headers["location"]
        if isinstance(need, requirement.InteractionRequired):
            self.log.emit(
                Kind.HOLD,
                f"PS が本人の判断を待っている（{what}）。agent は本人に URL とコードを見せて待つ",
                {"where": "person_server", "url": need.url, "code": need.code},
                spec="§11.6.3.2",
            )
            await self.on_interaction(InteractionPrompt(need.url, need.code, what))
        while True:
            response = await self.signed(
                "GET", location, self.agent_token, headers={"prefer": f"wait={POLL_WAIT_SECONDS}"}
            )
            if response.status_code != 202:
                if response.status_code == 200:
                    self.log.emit(Kind.RESUME, "PS の判断が出た → 処理を再開", spec="§11.8.4")
                else:
                    p = _problem(response)
                    self.log.emit(
                        Kind.REJECT,
                        f"PS から {response.status_code} {p.error}",
                        {"detail": p.detail},
                        spec="§11.9.4",
                    )
                return response
            await asyncio.sleep(float(response.headers.get("retry-after", "5")))


async def enroll(
    agent_provider: ServerId,
    http: httpx.AsyncClient,
    resolver: KeyResolver,
    log: EventLog,
    on_interaction: InteractionHandler,
) -> Agent:
    key = SigningKey.generate("agent")
    response = await http.post(
        f"{agent_provider}/lab/enroll", json={"jwk": key.public_jwk().model_dump()}
    )
    response.raise_for_status()
    token = _EnrollBody.model_validate_json(response.content).agent_token
    log.emit(Kind.INFO, "agent provider に登録し agent token を取得", spec="§5.3")
    return Agent(key, token, http, resolver, log, on_interaction)


class _EnrollBody(BaseModel):
    agent_token: str
