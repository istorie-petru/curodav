# Public deployment: Cloudflare Tunnel + Radicale (DAVx5 access)

Scope: `documentation/plans/open.md`'s "DAVx5 mobile access (Phase C)" --
a phone running DAVx5 syncs CalDAV/CardDAV against Radicale, reachable
over the public internet through a Cloudflare Tunnel, with real bcrypt
auth on the Radicale side. Pure infra, no app code -- everything here is
scripts/config, run once on the server.

This assumes the webapp itself is already deployed on this same host via
[`scripts/curodav-ctl`](../scripts/curodav-ctl) (see the repo root
`README.md`'s own "Deployment" section) -- `curodav.service` already
listens on `127.0.0.1:8000` before any of this runs.

## Why Cloudflare Tunnel instead of a reverse proxy + Let's Encrypt

`cloudflared` (Cloudflare's tunnel daemon) makes an **outbound-only**
connection from this server out to Cloudflare's network. Cloudflare
terminates TLS at their edge and forwards traffic down that tunnel to
whatever's listening locally -- so there's no inbound port to open, no
cert to issue/renew, and no reverse proxy (Caddy, nginx, ...) to run on
this host at all. `firewall.sh` reflects that: only SSH stays open.

## What this adds

```
Internet
   |
   |  Cloudflare's edge (TLS, DDoS protection, etc.)
   v
cloudflared  (outbound tunnel from this host -- no inbound port opened)
   |
   +--  https://DOMAIN_APP  --> localhost:8000  (curodav, already running)
   |
   +--  https://DOMAIN_DAV  --> localhost:5232  (radicale, installed here)
```

Radicale itself still binds loopback-only
(`radicale/config.template`'s `hosts = 127.0.0.1:5232`) and is the SAME
server the webapp already syncs against locally (`CC_RADICALE_URL` in
`/srv/curodav/shared/.env`) -- this doesn't add a second Radicale, it
makes the existing one reachable from outside too, over its own
subdomain, with real auth, via the tunnel.

## Prerequisites

1. **A domain already onboarded to your Cloudflare account** (its
   nameservers point at Cloudflare -- this is the free "add a site" flow
   in the Cloudflare dashboard if you haven't done it yet). Unlike a
   plain reverse-proxy setup, you do **not** need to create any A/AAAA
   records by hand -- `cloudflared tunnel route dns` creates the CNAME
   pointing at the tunnel for you, as part of step 4 below.
2. **Root/sudo SSH access** to the same Debian 12 host `curodav-ctl`
   deployed the app to.
3. A way to open a URL in a browser during setup, on any device (phone,
   laptop) -- `cloudflared tunnel login` (step 4) prints an authorization
   link you open once to link this server to your Cloudflare account.

## Setup, in order

```bash
cd deploy
cp deploy.env.example deploy.env
nano deploy.env          # fill in DOMAIN_APP, DOMAIN_DAV, TUNNEL_NAME, RADICALE_USER

sudo ./firewall.sh                       # lock down to ssh only
sudo ./cloudflared/install-cloudflared.sh  # installs cloudflared, creates the tunnel, routes DNS, starts it
sudo ./radicale/install-radicale.sh        # installs Radicale as its own service, prompts for a password
```

`cloudflared/install-cloudflared.sh` will pause partway through and print
a URL the first time it runs (`cloudflared tunnel login`) -- open that
link in a browser, log into Cloudflare, and pick the zone that owns
`DOMAIN_APP`/`DOMAIN_DAV`. The script waits for that to complete before
continuing; re-running the script afterward is a no-op for anything
already done (reuses the existing tunnel, existing login, etc.).

`install-radicale.sh` prints the exact lines to add next. Add them to
`/srv/curodav/shared/.env`:

```ini
CC_RADICALE_URL=http://127.0.0.1:5232/<RADICALE_USER>/
CC_RADICALE_USER=<RADICALE_USER>
CC_RADICALE_PASSWORD=<the password you just set>
```

(the app talks to Radicale directly over loopback -- it never goes
through the tunnel for its own sync, only DAVx5 does), then:

```bash
sudo systemctl restart curodav
```

## Configuring DAVx5 on the phone

Add an account with:

| Field    | Value                                    |
|----------|-------------------------------------------|
| URL      | `https://<DOMAIN_DAV>/<RADICALE_USER>/`   |
| Username | `<RADICALE_USER>`                         |
| Password | the password set in `install-radicale.sh` |

DAVx5 should discover the calendar/task-list/address-book collections
Radicale exposes under that user automatically.

## Verifying end to end

1. In the webapp, `/published-lists` -> create a list with visibility
   **Private**. Confirm its "Radicale link" shows a `subscribe_url` under
   `http://127.0.0.1:5232/...` (this is the app's own internal view of it;
   normal and expected to be loopback, not the public DAV domain).
2. On the phone, refresh DAVx5's sync -- the new list's collection should
   appear.
3. `sudo journalctl -u cloudflared -f` and `sudo journalctl -u radicale -f`
   while syncing, if it doesn't show up, to see the actual request/auth
   failure rather than guessing.

## Troubleshooting notes (unverified -- no live tunnel tested from this repo)

- If DAVx5 can reach `DOMAIN_APP` fine but `DOMAIN_DAV` requests get
  blocked or return an unexpected challenge page, check the Cloudflare
  dashboard's Security settings for that zone (Bot Fight Mode / WAF
  managed rules occasionally flag non-browser clients making
  `PROPFIND`/`REPORT` requests). A WAF skip rule scoped to `DOMAIN_DAV`
  is the usual fix; not pre-configured here since it depends on your
  specific zone's settings.
- `cloudflared tunnel route dns` can fail if a DNS record for that
  hostname already exists and points somewhere else -- the script prints
  a warning and keeps going rather than aborting; check the Cloudflare
  DNS tab for that zone if either hostname doesn't resolve afterward.

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
| `deploy.env.example`                 | Copy to `deploy.env`, fill in your real domains       |
| `firewall.sh`                        | ufw lockdown: only ssh open externally                |
| `cloudflared/config.yml.template`    | Tunnel ingress rules (hostname -> local port)          |
| `cloudflared/cloudflared.service`    | systemd unit for the tunnel daemon                     |
| `cloudflared/install-cloudflared.sh` | Installs cloudflared, creates/reuses the tunnel, routes DNS, starts it |
| `radicale/config.template`           | Production Radicale config (loopback, bcrypt auth)     |
| `radicale/radicale.service`          | systemd unit for Radicale                              |
| `radicale/install-radicale.sh`       | Creates the `radicale` user/venv/service, sets a password |

Nothing here is wired into CI (`.github/workflows/deploy.yml` only ever
runs `curodav-ctl update`) -- this is a one-time setup you run by hand on
the server, not something re-run on every push.
