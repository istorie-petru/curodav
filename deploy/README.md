# Public deployment: Cloudflare Tunnel + Radicale (DAVx5 access)

Scope: `documentation/plans/open.md`'s "DAVx5 mobile access (Phase C)" --
a phone running DAVx5 syncs CalDAV/CardDAV against Radicale, reachable
over the public internet through a Cloudflare Tunnel, with real bcrypt
auth on the Radicale side. Pure infra, no app code (aside from one small
Settings display field, see "Published Lists" below) -- everything here
is scripts/config, run once on the server.

This assumes the webapp itself is already deployed on this same host via
[`scripts/curodav-ctl`](../scripts/curodav-ctl) (see the repo root
`README.md`'s own "Deployment" section) -- `curodav.service` already
listens on `127.0.0.1:8000` before any of this runs.

## One hostname, not two

Radicale is reachable at `https://DOMAIN_APP/radicale/` -- a **path**
under the app's own hostname, not a second subdomain. Only one DNS
record, one Cloudflare Tunnel, one ingress rule ever gets created for
this app. This matters because cloudflared's ingress only routes by
*hostname*, never by path -- so splitting `/radicale/*` off from
everything else has to happen locally, after the tunnel, which is what
the new `nginx/` piece here does.

## Why Cloudflare Tunnel instead of a reverse proxy + Let's Encrypt

`cloudflared` (Cloudflare's tunnel daemon) makes an **outbound-only**
connection from this server out to Cloudflare's network. Cloudflare
terminates TLS at their edge and forwards traffic down that tunnel to
whatever's listening locally -- so there's no inbound port to open and no
cert to issue/renew. A local nginx still runs (see below), but purely to
split one hostname's traffic by path between two local services -- it
does no TLS of its own and isn't reachable from outside. `firewall.sh`
reflects the overall posture: only SSH stays open to the internet.

## What this adds

```
Internet
   |
   |  Cloudflare's edge (TLS, DDoS protection, etc.)
   v
cloudflared  (outbound tunnel from this host -- no inbound port opened)
   |
   v
https://DOMAIN_APP  -->  localhost:8080 (nginx, ONE ingress rule, ONE hostname)
                            |
                            +-- /radicale/*  --> localhost:5232 (radicale)
                            |     (rate-limited per real client IP -- see
                            |      "Rate limiting Radicale's auth" below)
                            +-- everything else --> localhost:8000 (curodav)
```

Radicale itself still binds loopback-only
(`radicale/config.template`'s `hosts = 127.0.0.1:5232`) and is the SAME
server the webapp already syncs against locally (`CC_RADICALE_URL` in
`/srv/curodav/shared/.env`) -- this doesn't add a second Radicale, it
makes the existing one reachable from outside too, under a path on the
app's own hostname, with real auth, via the tunnel and nginx.

nginx forwards the full, unmodified request path (including `/radicale/`)
to Radicale along with an `X-Script-Name: /radicale` header, rather than
stripping the prefix itself -- Radicale needs to know that prefix to
generate correctly-prefixed links in its own WebDAV responses (see
`nginx/curodav.nginx.conf.template`'s own comments for why getting this
backwards silently breaks a DAVx5 client's follow-up requests).

## How automated this is

`curodav-ctl install --dav` (below) does essentially everything itself.
Fully automated, no input needed: installing `cloudflared` from
Cloudflare's apt repo, creating (or reusing, if one with that name
already exists) the named Tunnel via the Cloudflare API, routing DNS for
your domain at that tunnel (`cloudflared tunnel route dns` creates the
actual CNAME record in your Cloudflare zone -- you never touch the DNS
dashboard), rendering `cloudflared/config.yml`, creating dedicated
unprivileged system users, installing/enabling all three systemd units,
and locking the firewall down to SSH-only. Radicale and nginx get the
same treatment: user, venv/package install, config, systemd unit, all
scripted.

Two things need a human, both one-time per host: your domain's
nameservers have to already point at Cloudflare (see "Prerequisites"
below -- the script can't register a domain or change nameservers for
you), and the very first run pauses for `cloudflared tunnel login`,
which prints a URL you open in a browser to authorize this host against
your Cloudflare account. That authorization persists
(`/root/.cloudflared/cert.pem`), so every later run skips straight past
it.

The rest is interactive but trivial: it prompts for the public hostname,
tunnel name, and Radicale username (remembering your previous answers as
defaults, so re-running to fix a typo doesn't mean retyping everything),
plus a Radicale password the first time. The whole thing is safe to
re-run any time -- it detects what already exists (repo, tunnel, DNS
route, Radicale account, systemd units) and only does the work that's
actually still missing, rather than tearing anything down and starting
over.

## Prerequisites

1. **A domain already onboarded to your Cloudflare account** (its
   nameservers point at Cloudflare -- this is the free "add a site" flow
   in the Cloudflare dashboard if you haven't done it yet). Unlike a
   plain reverse-proxy setup, you do **not** need to create any A/AAAA
   records by hand -- `cloudflared tunnel route dns` creates the CNAME
   pointing at the tunnel for you, as part of setup below.
2. **Root/sudo SSH access** to the same Debian 12 host `curodav-ctl`
   deployed the app to.
3. A way to open a URL in a browser during setup, on any device (phone,
   laptop) -- `cloudflared tunnel login` prints an authorization link you
   open once to link this server to your Cloudflare account.

## Setup: one command (recommended)

```bash
sudo curodav-ctl install --dav
```

This is `scripts/curodav-ctl`'s own orchestration of everything below: the
first time it runs, it asks for `DOMAIN_APP`/`TUNNEL_NAME`/`RADICALE_USER`
and a Radicale password, then runs `firewall.sh`,
`radicale/install-radicale.sh`, `nginx/install-nginx.sh`, and
`cloudflared/install-cloudflared.sh` in that order, then writes
`CC_RADICALE_URL`/`CC_RADICALE_USER`/`CC_RADICALE_PASSWORD`/
`CC_RADICALE_PUBLIC_URL` into `/srv/curodav/shared/.env` itself and
restarts `curodav.service` -- no manual file editing. It also runs
automatically at the end of a plain `curodav-ctl install` if you answer
yes to the "set up DAV now?" prompt there, and every `curodav-ctl update`
re-checks reachability (Radicale's own loopback port, nginx's local path
route, and the public hostname once this has been run once) as a
warn-only, non-blocking step.

Values are persisted to `/srv/curodav/shared/deploy.env` (outside any
release directory, so they survive `update`'s disposable git clones).
**Re-running `install --dav` later is a no-op on the prompts** -- it
reuses `DOMAIN_APP`/`TUNNEL_NAME`/`RADICALE_USER` and leaves an already-set
Radicale password untouched, rather than asking again every time. Pass
`--reconfigure` when you actually want to change any of those (including
rotating the password):

```bash
sudo curodav-ctl install --dav --reconfigure
```

`--proxy=manual` skips the Cloudflare-specific step entirely (installing
`cloudflared`, creating a tunnel, routing DNS) while still setting up
Radicale and the local nginx path-router -- for anyone fronting this host
with their own reverse proxy, tunnel provider, or Caddy/nginx instead. See
"Bringing your own reverse proxy" below for the walkthrough. Default is
`--proxy=cloudflare`, i.e. today's behavior, unchanged if you never pass
the flag.

`cloudflared/install-cloudflared.sh` will still pause partway through and
print a URL the first time it runs (`cloudflared tunnel login`) -- open
that link in a browser, log into Cloudflare, and pick the zone that owns
`DOMAIN_APP`. `curodav-ctl install --dav` waits for that like any other
interactive step.

To rotate just the Radicale password later without re-answering every
other prompt, `deploy/radicale/install-radicale.sh --reset-password` (see
"Rotating the Radicale password" below) still works standalone -- just
remember to also update `CC_RADICALE_PASSWORD` in `/srv/curodav/shared/.env`
yourself afterward, since that script alone doesn't know about `curodav-ctl`'s
env-wiring step.

## Setup: manual, step by step (what the command above actually does)

Useful if you want to run pieces individually, debug a failure, or you're
not using `curodav-ctl` at all.

```bash
cd deploy
cp deploy.env.example deploy.env
nano deploy.env          # fill in DOMAIN_APP, TUNNEL_NAME, RADICALE_USER

sudo ./firewall.sh                       # lock down to ssh only
sudo ./radicale/install-radicale.sh        # installs Radicale as its own service, prompts for a password
sudo ./nginx/install-nginx.sh              # local path router: /radicale/* -> :5232, / -> :8000
sudo ./cloudflared/install-cloudflared.sh  # installs cloudflared, creates the tunnel, routes DNS, starts it
```

`install-radicale.sh` prints the exact lines to add next. Add them to
`/srv/curodav/shared/.env`:

```ini
CC_RADICALE_URL=http://127.0.0.1:5232/<RADICALE_USER>/
CC_RADICALE_USER=<RADICALE_USER>
CC_RADICALE_PASSWORD=<the password you just set>
CC_RADICALE_PUBLIC_URL=https://<DOMAIN_APP>/radicale/<RADICALE_USER>/
```

`CC_RADICALE_URL` stays the loopback address -- the app talks to Radicale
directly over `127.0.0.1`, never through nginx/the tunnel, for its own
sync. `CC_RADICALE_PUBLIC_URL` is display-only (currently just
Published Lists' "subscribe_url", see below) and is safe to leave unset
if you never expose Radicale publicly. Then:

```bash
sudo systemctl restart curodav
```

## Bringing your own reverse proxy

`--proxy=manual` (2026-09-18, direct request: "a clearer way to integrate
Cloudflare Tunnel or any other fix into that installer, because some users
might install it manually") is for anyone who doesn't want Cloudflare
Tunnel specifically -- their own Caddy/nginx + Let's Encrypt, a different
tunnel provider (Tailscale Funnel, ngrok, etc.), or a proxy on a separate
box entirely.

```bash
sudo curodav-ctl install --dav --proxy=manual
```

This still runs `firewall.sh`, `radicale/install-radicale.sh`, and
`nginx/install-nginx.sh` -- Radicale and the local nginx path-router are
proxy-agnostic, nginx just listens on `127.0.0.1:8080` and doesn't care
what connects to it. Only `cloudflared/install-cloudflared.sh` is skipped.
Everything else (writing `CC_RADICALE_*` into `/srv/curodav/shared/.env`,
restarting `curodav.service`) still happens exactly as it does with
`--proxy=cloudflare`.

What you need to do yourself afterward:

1. **Point your reverse proxy at `127.0.0.1:8080`** for both `/` and
   `/radicale/` under whatever public hostname you're using -- that's the
   one address nginx listens on here regardless of what sits in front of
   it. If your proxy runs on a *different* host than this one, you'll need
   to either open a port to it specifically (not `:8080` to the whole
   internet) or run your proxy on this same host.
2. **Terminate TLS yourself** -- Cloudflare Tunnel did that for you in the
   default flow; a manual setup needs its own certificate (Let's Encrypt
   via your proxy of choice is the usual answer).
3. **Check the rate-limit zone's IP source.** `install-nginx.sh` sets
   `/etc/nginx/conf.d/curodav-ratelimit.conf`'s client-IP source to
   `$remote_addr` in `--proxy=manual` mode (rather than Cloudflare's
   `CF-Connecting-IP` header) -- correct if your proxy also runs on this
   host and connects to nginx over loopback without spoofing forwarding
   headers. If your setup is different (e.g. your proxy sets its own
   `X-Real-IP`/`X-Forwarded-For` and you want to key off that instead),
   hand-edit that file's `map` block and `systemctl reload nginx` -- see
   "Rate limiting Radicale's auth" below for what it's protecting against.
4. **`CC_RADICALE_PUBLIC_URL`** is still built from the `DOMAIN_APP` you
   gave the installer (`https://DOMAIN_APP/radicale/RADICALE_USER/`) --
   make sure that's the actual public hostname your own proxy answers on,
   not a placeholder.

## Configuring DAVx5 on the phone

Add an account with:

| Field    | Value                                              |
|----------|------------------------------------------------------|
| URL      | `https://<DOMAIN_APP>/radicale/<RADICALE_USER>/`    |
| Username | `<RADICALE_USER>`                                   |
| Password | the password set in `install-radicale.sh`           |

DAVx5 should discover the calendar/task-list/address-book collections
Radicale exposes under that user automatically.

## Published Lists

`/published-lists`' "Radicale link" (`subscribe_url`) reads
`CC_RADICALE_PUBLIC_URL` when it's set (config.py's
`radicale_public_base_url`, `routers/published_lists.py`'s `list_index`)
and falls back to the loopback `CC_RADICALE_URL` otherwise -- the same
loopback-only behavior this page always had before `CC_RADICALE_PUBLIC_URL`
existed. If you've run `install --dav`, this is wired automatically; if
you set things up manually, make sure you added `CC_RADICALE_PUBLIC_URL`
per the step above, or that page will keep showing an address that only
resolves on this host.

## Verifying end to end

1. In the webapp, `/published-lists` -> create a list with visibility
   **Private**. Confirm its "Radicale link" shows a `subscribe_url` under
   `https://DOMAIN_APP/radicale/...` (if it still shows
   `http://127.0.0.1:5232/...`, `CC_RADICALE_PUBLIC_URL` isn't set --
   see "Published Lists" above).
2. On the phone, refresh DAVx5's sync -- the new list's collection should
   appear.
3. `sudo journalctl -u cloudflared -f`, `sudo journalctl -u nginx -f`, and
   `sudo journalctl -u radicale -f` while syncing, if it doesn't show up,
   to see the actual request/auth failure rather than guessing which of
   the three hops it's failing at.

## Rate limiting Radicale's auth

Radicale's own auth (`htpasswd` + bcrypt, `radicale/config.template`) has
no rate limiting or lockout of its own -- unlike curodav's own login
(`src/auth.py`'s `login_rate_limited`, a 5-attempts-per-15-minutes per-IP
throttle), nothing stops an unlimited number of password guesses. Two
approaches that DON'T work here, and why, before the one that does:

- **fail2ban watching Radicale's log, banning via iptables/ufw.** Doesn't
  work at all in this setup: `firewall.sh` closes every inbound port
  except SSH, and the only thing that ever connects to nginx/Radicale is
  `cloudflared`, over loopback (see "Why Cloudflare Tunnel" above). There
  is no inbound connection from the actual attacker's IP for a local
  firewall rule to ever block -- banning an IP on this host blocks nothing
  at Cloudflare's edge.
- **A Cloudflare WAF rate-limiting rule**, scoped to `/radicale/*`, would
  work and stop requests before they even reach the tunnel -- genuinely
  the stronger fix. Not automated here: it needs a scoped Cloudflare API
  token this tooling never collects (`cloudflared tunnel login`'s
  cert.pem authorizes tunnel/DNS operations only, not zone-level WAF
  rules), so it's a manual one-time step in the dashboard (Security >
  WAF > Rate limiting rules on the zone that owns `DOMAIN_APP`) if you
  want it in addition to what's below.

What's actually wired in by default: **nginx's own `limit_req`**, applied
to the `/radicale/` location only
(`curodav.nginx.conf.template`/`curodav-ratelimit.conf.template`, installed by
`install-nginx.sh`). This caps sustained request rate to ~10/minute per
real client IP (a burst of 40 absorbed instantly -- one full DAVx5/
Thunderbird/iOS sync cycle's PROPFIND/REPORT/GET requests -- before
anything is throttled), turning an unattended guessing loop into "at most
~14,400 attempts/day" instead of unlimited, on top of bcrypt's own
per-attempt cost. Keyed on Cloudflare's `CF-Connecting-IP` header, not
nginx's own `$remote_addr` -- the latter is *always* `127.0.0.1` here
(cloudflared is the only thing that ever connects to nginx), so rate-
limiting on it would either throttle every real client as one shared
bucket or (set high enough to avoid that) not throttle an attacker at
all. `CF-Connecting-IP` is set by Cloudflare's edge from the real TCP
connection and can't be spoofed by a client-supplied header of the same
name.

A 429 response on `/radicale/*` (visible in a DAVx5 sync log, or via
`sudo journalctl -u nginx | grep 'limiting requests'`) means this limit
was hit -- either a real client syncing unusually often (raise the
`rate=`/`burst=` values in `/etc/nginx/conf.d/curodav-ratelimit.conf` --
the file `install-nginx.sh` generates from `nginx/curodav-ratelimit.conf.template` --
and `systemctl reload nginx`), or exactly the abuse this exists to catch.

## Troubleshooting notes (unverified -- no live tunnel tested from this repo)

- If DAVx5 can reach `DOMAIN_APP` fine but `DOMAIN_APP/radicale/...`
  requests get blocked or return an unexpected challenge page, check the
  Cloudflare dashboard's Security settings for that zone (Bot Fight Mode /
  WAF managed rules occasionally flag non-browser clients making
  `PROPFIND`/`REPORT` requests). A WAF skip rule scoped to the
  `/radicale/*` path is the usual fix; not pre-configured here since it
  depends on your specific zone's settings.
- A 502 on `/radicale/*` specifically (but `/` working fine) usually means
  nginx is up but Radicale isn't -- check `systemctl status radicale`.
  `nginx -t` catches config syntax issues; `journalctl -u nginx -e`
  catches everything else nginx-side.
- `cloudflared tunnel route dns` can fail if a DNS record for that
  hostname already exists and points somewhere else -- the script prints
  a warning and keeps going rather than aborting; check the Cloudflare
  DNS tab for that zone if the hostname doesn't resolve afterward.

## Checking things are still set up correctly

```bash
curodav-ctl status
```

No `sudo` needed and touches nothing -- runs the same reachability checks
`update`/`install --dav` already run as a side effect (loopback, the local
nginx path-route, and the public hostname if `deploy.env` exists), plus a
consistency check that `CC_RADICALE_URL` and `CC_RADICALE_PUBLIC_URL` in
`/srv/curodav/shared/.env` still agree on which Radicale user they point
at. Useful any time you've hand-edited the env file, rotated
`RADICALE_USER`, or just want a "is this actually working" answer without
digging through `journalctl`. The app's own Settings > Data & Maintenance
page (2026-09-13) covers the complementary question -- which of env file /
database / dev-default this *process* is actually running with right now,
whether the env file has drifted from what's loaded, and a one-click live
"Test connection" -- from inside the browser instead of SSH.

## Rotating the Radicale password

```bash
sudo ./radicale/install-radicale.sh --reset-password
```

Then update `CC_RADICALE_PASSWORD` in `/srv/curodav/shared/.env`, restart
`curodav`, and update the password saved in DAVx5 on the phone -- all
three (Radicale's own hash, the webapp's env, DAVx5's saved credential)
need to agree, there's no propagation between them.

## Files in this directory

| File                                | Purpose                                             |
|--------------------------------------|------------------------------------------------------|
| `deploy.env.example`                 | Copy to `deploy.env`, fill in your real domain        |
| `firewall.sh`                        | ufw lockdown: only ssh open externally                |
| `nginx/curodav.nginx.conf.template`  | Local path router: `/radicale/*` -> :5232, `/` -> :8000 |
| `nginx/curodav-ratelimit.conf.template` | Rate-limit zone for `/radicale/*` (see "Rate limiting Radicale's auth" above) |
| `nginx/install-nginx.sh`             | Installs nginx, drops in the site config + rate-limit zone, restarts |
| `cloudflared/config.yml.template`    | Tunnel ingress rule (ONE hostname -> nginx's port)     |
| `cloudflared/cloudflared.service`    | systemd unit for the tunnel daemon                     |
| `cloudflared/install-cloudflared.sh` | Installs cloudflared, creates/reuses the tunnel, routes DNS, starts it |
| `radicale/config.template`           | Production Radicale config (loopback, bcrypt auth)     |
| `radicale/radicale.service`          | systemd unit for Radicale                              |
| `radicale/install-radicale.sh`       | Creates the `radicale` user/venv/service, sets a password |

Nothing here is wired into CI (`.github/workflows/deploy.yml` only ever
runs `curodav-ctl update`, unattended over SSH -- it never installs or
reconfigures DAV, only checks reachability). Setting DAV up at all, whether
via `curodav-ctl install --dav` or the manual steps above, is something you
run by hand once, interactively, not something that fires on every push.
