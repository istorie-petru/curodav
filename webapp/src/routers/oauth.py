"""The OAuth 2.0 server for Claude connectors and other apps: discovery documents, client registration, consent, tokens.

Feature document: curodav-notes/documentation/features/api-and-mcp.md

Discovery, registration and the token endpoint are public (auth.API_PATHS); the consent page sits behind the normal
login, so only someone signed in to Curodav can let an app in. On an install without a login nothing can be approved.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import access_tokens, auth, db
from ..api_auth import base_url
from ..deps import get_db, templates

router = APIRouter(tags=["oauth"])

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_AUTHORIZE_FIELDS = ("client_id", "redirect_uri", "response_type", "scope", "state", "code_challenge", "code_challenge_method", "resource")


def _oauth_error(exc: access_tokens.OAuthError, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": exc.code, "error_description": str(exc)}, status_code=status, headers=_NO_STORE)


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource(request: Request):
    return JSONResponse(access_tokens.protected_resource_metadata(base_url(request)))


@router.get("/.well-known/oauth-authorization-server")
def authorization_server(request: Request):
    return JSONResponse(access_tokens.authorization_server_metadata(base_url(request)))


@router.post("/oauth/register")
async def register(request: Request):
    try:
        metadata = await request.json()
    except ValueError:
        metadata = None
    with db.connect(request.app.state.settings.db_path, reuse_schema=True) as conn:
        try:
            return JSONResponse(access_tokens.register_client(conn, metadata), status_code=201, headers=_NO_STORE)
        except access_tokens.OAuthError as exc:
            return _oauth_error(exc)


@router.post("/oauth/token")
async def token(request: Request):
    form = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    with db.connect(request.app.state.settings.db_path, reuse_schema=True) as conn:
        try:
            return JSONResponse(access_tokens.token_request(conn, form), headers=_NO_STORE)
        except access_tokens.OAuthError as exc:
            return _oauth_error(exc)


def _approval_possible(request: Request, conn) -> bool:
    settings = request.app.state.settings
    return auth.auth_enabled(settings, conn) or auth.skip_auth_applies(settings, request.scope)


def _back_to_client(redirect_uri: str, params: dict[str, str]) -> RedirectResponse:
    joiner = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(url=f"{redirect_uri}{joiner}{urlencode(params)}", status_code=303)


def _consent_page(request: Request, context: dict, status: int = 200):
    return templates.TemplateResponse(request, "oauth_consent.html", context, status_code=status)


def _check(request: Request, conn, params: dict[str, str]):
    """(checked request, None) or (None, response): a bad client or address gets an error page, other faults go back."""
    try:
        return access_tokens.check_authorize_request(conn, params), None
    except access_tokens.OAuthError as exc:
        client = access_tokens.get_client(conn, params.get("client_id", ""))
        if client and params.get("redirect_uri") in client["redirect_uris"]:
            back = {"error": exc.code, "error_description": str(exc), "iss": base_url(request)}
            if params.get("state"):
                back["state"] = params["state"]
            return None, _back_to_client(params["redirect_uri"], back)
        return None, _consent_page(request, {"error": str(exc)}, status=400)


@router.get("/oauth/authorize")
def authorize_page(request: Request, conn=Depends(get_db)):
    if not _approval_possible(request, conn):
        return _consent_page(request, {"error": "Set a login for Curodav in Settings before connecting apps."}, status=403)
    params = {k: request.query_params.get(k, "") for k in _AUTHORIZE_FIELDS}
    checked, response = _check(request, conn, params)
    if response is not None:
        return response
    return _consent_page(request, {"error": None, "client_name": checked["client"]["client_name"],
                                   "redirect_host": checked["redirect_uri"].split("/")[2], "scopes": checked["scopes"].split(),
                                   "fields": params})


@router.post("/oauth/authorize")
async def authorize_decision(request: Request):
    form = await request.form()
    params = {k: str(form.get(k) or "") for k in _AUTHORIZE_FIELDS}
    with db.connect(request.app.state.settings.db_path, reuse_schema=True) as conn:
        if not _approval_possible(request, conn):
            return _consent_page(request, {"error": "Set a login for Curodav in Settings before connecting apps."}, status=403)
        checked, response = _check(request, conn, params)
        if response is not None:
            return response
        back = {"iss": base_url(request)}
        if checked["state"]:
            back["state"] = checked["state"]
        if form.get("decision") != "allow":
            return _back_to_client(checked["redirect_uri"], {"error": "access_denied", **back})
        return _back_to_client(checked["redirect_uri"], {"code": access_tokens.issue_code(conn, checked), **back})
