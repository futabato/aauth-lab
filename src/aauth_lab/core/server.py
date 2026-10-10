"""Server-side plumbing shared by AP, PS and Resource: signed-request verification,
problem+json errors (§11.9.2) and 202 deferred responses (§11.8.2)."""

from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from aauth_lab.core import httpsig, requirement
from aauth_lab.core.discovery import JwtErrorCode, JwtVerificationError, KeyResolver, verify_jwt
from aauth_lab.core.encoding import JsonObject
from aauth_lab.core.httpsig import SignatureErrorCode, SignatureFailure
from aauth_lab.core.keys import Jwk
from aauth_lab.core.tokens import (
    AgentTokenClaims,
    AuthTokenClaims,
    ClaimsBase,
    DecodedToken,
    PersonTokenClaims,
    TokenFormatError,
    peek_typ,
)


class ProblemError(Exception):
    """An AAuth error answered as application/problem+json (§11.9.2)."""

    def __init__(
        self,
        status: int,
        error: str,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
        extra: JsonObject | None = None,
    ) -> None:
        super().__init__(f"{status} {error}: {detail}")
        self.status = status
        self.error = error
        self.detail = detail
        self.headers = headers or {}
        self.extra = extra or {}


def problem_response(error: ProblemError) -> JSONResponse:
    body: JsonObject = {"error": error.error, **error.extra}
    if error.detail:
        body["detail"] = error.detail
    return JSONResponse(
        body, status_code=error.status, headers=error.headers, media_type="application/problem+json"
    )


def install_error_handlers(app: FastAPI) -> None:
    async def on_problem(_: Request, exc: Exception) -> Response:
        assert isinstance(exc, ProblemError)
        return problem_response(exc)

    async def on_signature(_: Request, exc: Exception) -> Response:
        assert isinstance(exc, SignatureFailure)
        # §11.9.1: the header, not the body, is the machine-readable carrier.
        headers = {"Signature-Error": exc.header_value()}
        if exc.code is SignatureErrorCode.UNSUPPORTED_SCHEME:
            headers["Accept-Signature-Scheme"] = "jwt"
        return JSONResponse({"detail": exc.detail}, status_code=401, headers=headers)

    app.add_exception_handler(ProblemError, on_problem)
    app.add_exception_handler(SignatureFailure, on_signature)


async def request_parts(request: Request) -> httpsig.RequestParts:
    raw_path = request.scope.get("raw_path")
    path = raw_path.decode() if isinstance(raw_path, bytes) else request.url.path
    return httpsig.RequestParts(
        method=request.method,
        authority=request.headers.get("host", ""),
        path=path.split("?")[0],
        headers={k.lower(): v for k, v in request.headers.items()},
        body=await request.body(),
    )


@dataclass(frozen=True)
class AgentTokenCall:
    token: DecodedToken[AgentTokenClaims]


@dataclass(frozen=True)
class PersonTokenCall:
    token: DecodedToken[PersonTokenClaims]


@dataclass(frozen=True)
class AuthTokenCall:
    token: DecodedToken[AuthTokenClaims]


type Presented = AgentTokenCall | PersonTokenCall | AuthTokenCall
"""What the agent put in Signature-Key — the answer to "who is asking, holding what"."""


@dataclass(frozen=True)
class VerifiedCall:
    presented: Presented
    parts: httpsig.RequestParts

    @property
    def key(self) -> Jwk:
        return self.presented.token.claims.cnf.jwk


async def _verified[C: ClaimsBase](
    raw: str, claims_type: type[C], resolver: KeyResolver
) -> DecodedToken[C]:
    try:
        return await verify_jwt(raw, claims_type, resolver)
    except JwtVerificationError as e:
        code = (
            SignatureErrorCode.EXPIRED_JWT
            if e.code is JwtErrorCode.EXPIRED
            else SignatureErrorCode.INVALID_JWT
        )
        raise SignatureFailure(code, e.detail) from e


async def verify_call(request: Request, resolver: KeyResolver) -> VerifiedCall:
    """§11.3.4 in full: structure, then the Signature-Key JWT, then the signature itself."""
    parts = await request_parts(request)
    parsed = httpsig.parse(parts)
    try:
        typ = peek_typ(parsed.token)
    except TokenFormatError as e:
        raise SignatureFailure(SignatureErrorCode.INVALID_JWT, str(e)) from e
    presented: Presented
    match typ:
        case "aa-agent+jwt":
            presented = AgentTokenCall(await _verified(parsed.token, AgentTokenClaims, resolver))
        case "aa-person+jwt":
            presented = PersonTokenCall(await _verified(parsed.token, PersonTokenClaims, resolver))
        case "aa-auth+jwt":
            presented = AuthTokenCall(await _verified(parsed.token, AuthTokenClaims, resolver))
        case _:
            raise SignatureFailure(SignatureErrorCode.INVALID_JWT, f"unexpected typ {typ!r}")
    httpsig.verify(parsed, parts, presented.token.claims.cnf.jwk)
    return VerifiedCall(presented, parts)


def deferred(
    location: str,
    *,
    retry_after: int,
    status: str = "pending",
    need: requirement.Requirement | None = None,
    extra: JsonObject | None = None,
) -> JSONResponse:
    """A 202 Accepted deferred response (§11.8.2)."""
    headers = {
        "Location": location,
        "Retry-After": str(retry_after),
        "Cache-Control": "no-store",
    }
    if need is not None:
        headers[requirement.HEADER] = requirement.serialize(need)
    body: JsonObject = {"status": status, **(extra or {})}
    return JSONResponse(body, status_code=202, headers=headers)


def challenge(need: requirement.Requirement) -> JSONResponse:
    """A 401 with AAuth-Requirement (§6.1, §6.4, §6.5)."""
    return JSONResponse(
        {"detail": "authorization required"},
        status_code=401,
        headers={requirement.HEADER: requirement.serialize(need)},
    )
