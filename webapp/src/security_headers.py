"""Security response headers (2026-08-29) -- a pure-ASGI middleware that
adds a fixed set of hardening headers to every HTTP response. Separate
module from auth.py: this has nothing to do with sessions/login, it's
about the browser-enforced protections every response gets regardless of
whether auth is even configured.

Headers added, and why:

  - `X-Content-Type-Options: nosniff` -- stops a browser from guessing a
    response's content type from its body (MIME-sniffing), which is how a
    file an attacker got the app to serve with the "wrong" content-type
    could otherwise be reinterpreted as HTML/JS.
  - `X-Frame-Options: DENY` + CSP's `frame-ancestors 'none'` -- this app
    has no legitimate reason to ever render inside another site's
    <iframe> (clickjacking defense). Two headers for the same thing
    because `frame-ancestors` is the modern replacement but some older
    user agents only honor X-Frame-Options.
  - `Referrer-Policy: strict-origin-when-cross-origin` -- a browser's
    default is looser than this; worth tightening now that Published
    Lists' public links (routers/public_lists.py) put an unguessable
    token in a URL path -- this stops that token leaking into a
    cross-origin Referer header if a page ever links out from a
    public-list-adjacent view. Same-origin navigation still gets the full
    path (needed for this app's own `?next=`/`?note=` query-param
    conventions), only cross-origin requests get trimmed to just the
    origin.
  - `Content-Security-Policy` -- see CSP_POLICY's own comment below for
    how script-src/style-src are locked down.
  - `Strict-Transport-Security` (HSTS) -- only added when the request's
    own scheme is "https" (both deploys already pass uvicorn
    `--proxy-headers`, so this is accurate behind a TLS-terminating
    reverse proxy too, same reasoning as auth.py's `is_secure_request`).
    Sending HSTS over a plain-HTTP response is pointless (browsers ignore
    it unless it arrived over HTTPS) and would be actively confusing on
    this app's common LAN/Tailscale-over-HTTP deployment, so it's
    deliberately conditional rather than unconditional.

CSP nonces (2026-09-07, audit-fixes-2.0.md item 11 -- `'unsafe-inline'`
fully eliminated from both script-src and style-src): every inline
<script>/<style> tag left in this app's templates now carries a
per-request nonce (`{{ csp_nonce() }}`, a Jinja global -- see
deps.py::_csp_nonce), and every `onclick=`/`onchange=`/`style=`
attribute that used to rely on `'unsafe-inline'` has been rewritten --
event delegation in static JS for the handlers, CSSOM `.style` writes
for server-computed values, plain CSS classes for fixed ones. Nothing in
this app's markup needs `'unsafe-inline'` anymore.

`CSP_POLICY` below is a template string (`{nonce}` placeholder), not a
fixed value: `SecurityHeadersMiddleware.__call__` generates a fresh
`secrets.token_urlsafe(16)` nonce per request, stashes it on
`scope["state"]["csp_nonce"]` *before* calling `self.app` -- Starlette's
`Request.state` property lazily reads `scope["state"]` (see
`starlette/requests.py`), so any `Request` FastAPI builds off this same
scope downstream -- including the one Jinja2Templates injects into every
template context -- sees `request.state.csp_nonce`, matching the nonce
this middleware puts in the response header -- and formats
`CSP_POLICY.format(nonce=nonce)` into the actual header value, giving
`script-src 'self' 'nonce-<value>'` / `style-src 'self'
'nonce-<value>'` with no `'unsafe-inline'` anywhere in the policy."""

from __future__ import annotations

import secrets

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'nonce-{nonce}'; "
    "style-src 'self' 'nonce-{nonce}'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)

HSTS_VALUE = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware:
    """Pure-ASGI, no settings/state dependency -- unlike AuthMiddleware/
    CSRFMiddleware, these headers apply unconditionally to every response,
    auth enabled or not. Wraps `send` to inject headers onto the
    http.response.start event, the same technique GZipMiddleware/
    Starlette's own middlewares use to add headers without buffering the
    whole response body."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        is_https = scope.get("scheme") == "https"

        # Per-request nonce, stashed on scope["state"] *before* calling
        # self.app so that any Request FastAPI/Starlette builds off this
        # scope downstream -- including the one Jinja2Templates injects
        # into every template context -- sees the same value via
        # `request.state.csp_nonce` (Request.state lazily reads
        # scope["state"], see module docstring). token_urlsafe(16) gives
        # 128 bits of randomness, base64url-encoded -- short enough for a
        # header/attribute, long enough that guessing it is infeasible.
        nonce = secrets.token_urlsafe(16)
        scope.setdefault("state", {})["csp_nonce"] = nonce
        csp_value = CSP_POLICY.format(nonce=nonce)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-frame-options", b"DENY"))
                headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
                headers.append((b"content-security-policy", csp_value.encode("ascii")))
                if is_https:
                    headers.append((b"strict-transport-security", HSTS_VALUE.encode("ascii")))
            await send(message)

        return await self.app(scope, receive, send_wrapper)
