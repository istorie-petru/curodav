# Security policy

## Supported versions

Only the latest tagged release is supported. Curodav is a single-maintainer, single-user-focused project — there's no long-term support branch for older versions. If you're running an old release and hit a security issue, please update to the latest `main`/tag first and confirm it still reproduces before reporting.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for a security vulnerability. Instead, use GitHub's private [Security Advisories](../../security/advisories/new) feature for this repository, if available, or contact the maintainer directly through the contact information on their GitHub profile.

Include what you can: steps to reproduce, the affected version or commit, and what you'd expect to happen instead. This is a small project maintained by one person in their spare time — expect a reasonable-effort response, not an SLA.

## Threat model and known limits

Curodav is designed to be self-hosted on a trusted network (like [Tailscale](https://tailscale.com/)) or behind something that terminates TLS and/or authenticates on its behalf. It is **not** designed to be exposed directly to the open internet with no protection in front of it. Specifically:

- **No TLS of its own.** The app speaks plain HTTP. Put it behind a VPN, a reverse proxy, or a tunnel (like Cloudflare Tunnel — see the deploy documentation) that adds TLS before it's reachable from anywhere you don't fully trust.
- **Login is opt-in for local/manual runs, required for production deploys.** See the Wiki's [Authentication](../../wiki/Features-Authentication) page for exactly when it's enforced. Login rate-limiting is a simple in-memory per-IP window, not account lockout or CAPTCHA.
- **Single account, no password reset flow.** There's one login for the whole app, by design — this isn't a multi-tenant system. See the troubleshooting section of the [README](README.md) for recovering a forgotten password (it requires direct database access; there's no self-service reset).
- **A Published List's public link is intentionally unauthenticated** once you turn it on — that's the point of the feature (sharing a filtered calendar/contact feed with someone else), not an oversight. See the Wiki's [Published Lists](../../wiki/Features-Published-Lists) page.

If you're deploying this publicly (not just on a home network or VPN), read the deploy documentation's security notes before doing so.

## Dependencies

Curodav pins its dependencies via `uv.lock`. If you discover a vulnerability in a dependency this project uses, please report it upstream to that project as well as here if it materially affects Curodav's own security posture.
