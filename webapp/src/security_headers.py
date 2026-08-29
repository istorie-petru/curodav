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
    the specific tradeoff this app makes.
  - `Strict-Transport-Security` (HSTS) -- only added when the request's
    own scheme is "https" (both deploys already pass uvicorn
    `--proxy-headers`, so this is accurate behind a TLS-terminating
    reverse proxy too, same reasoning as auth.py's `is_secure_request`).
    Sending HSTS over a plain-HTTP response is pointless (browsers ignore
    it unless it arrived over HTTPS) and would be actively confusing on
    this app's common LAN/Tailscale-over-HTTP deployment, so it's
    deliberately conditional rather than unconditional.

CSP tradeoff, stated plainly: this app's templates use inline
<script>/<style> and inline event-handler attributes throughout (see e.g.
login.html's inline theme-detection script, or the many `onclick=...`
attributes across templates) -- a strict, nonce-based CSP would need
threading a per-request nonce through every template and rewriting every
inline handler, a large refactor out of scope for this slice. CSP_POLICY
below still meaningfully restricts what a successful XSS could do
(no cross-origin script/object/frame loading, no arbitrary form
submission target, no framing) via `'unsafe-inline'` on script-src/
style-src rather than nonces -- a real gap versus a fully strict policy,
called out explicitly rather than left implicit."""

from __future__ import annotations

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
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

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-frame-options", b"DENY"))
                headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
                headers.append((b"content-security-policy", CSP_POLICY.encode("ascii")))
                if is_https:
                    headers.append((b"strict-transport-security", HSTS_VALUE.encode("ascii")))
            await send(message)

        return await self.app(scope, receive, send_wrapper)
