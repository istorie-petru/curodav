# Public deployment: Caddy + Radicale (DAVx5 access)

Scope: `documentation/plans/open.md`'s "DAVx5 mobile access (Phase C)" --
a phone running DAVx5 syncs CalDAV/CardDAV against Radicale through a
public HTTPS reverse proxy (Caddy) with real bcrypt auth. Pure infra, no
app code -- everything here is scripts/config, run once on the server.

This assumes the webapp itself is already deployed on this same host via
[`scripts/curodav-ctl`](../scripts/curodav-ctl) (see the repo root
`README.md`'s own "Deployment" section) -- `curodav.service` already
listens on `127.0.0.1:8000` before any of this runs.

## What this adds

```
Internet
   |
   |  :80, :443 (only these two ports are open externally -- firewall.sh)
   v
 Caddy  (deploy/Caddyfile.template, TLS via Let's Encrypt)
   |
   +--  https://DOMAIN_APP  --> 127.0.0.1:8000  (curodav, already running)
   |
   +--  https://DOMAIN_DAV  --> 127.0.0.1:5232  (radicale, installed here)
```

Radicale itself binds loopback-only (`radicale/config.template`'s
`hosts = 127.0.0.1:5232`) and is the SAME server the webapp already syncs
against locally (`CC_RADICALE_URL` in `/srv/curodav/shared/.env`) -- this
doesn't add a second Radicale, it makes the existing one reachable from
outside too, over its own subdomain, with real auth.

## Prerequisites

1. **A domain you control DNS for.** Create two A (and/or AAAA) records
   pointing at this server's public IP:
   - `DOMAIN_APP` (e.g. `app.example.com`) -- the webapp
   - `DOMAIN_DAV` (e.g. `dav.example.com`) -- Radicale, what DAVx5 points at

   Use a **separate subdomain** for DAV, not a path under the app's own
   domain -- Radicale's `/‹user›/‹collection›/` URL layout would otherwise
   collide with the webapp's own routes on the same hostname.

   Wait for DNS to actually resolve (`dig +short DOMAIN_APP`,
   `dig +short DOMAIN_DAV`) before running `install-caddy.sh` -- Caddy's
   automatic HTTPS needs the domain to already point here to complete the
   ACME challenge.

2. **Root/sudo SSH access** to the same Debian 12 host `curodav-ctl`
   deployed the app to.

## Setup, in order

```bash
cd deploy
cp deploy.env.example deploy.env
nano deploy.env          # fill in DOMAIN_APP, DOMAIN_DAV, LE_EMAIL, RADICALE_USER

sudo ./firewall.sh                     # lock down to 22/80/443 only
sudo ./install-caddy.sh                # installs Caddy, gets TLS certs, proxies both domains
sudo ./radicale/install-radicale.sh    # installs Radicale as its own service, prompts for a password
```

`install-radicale.sh` prints the exact lines to add next. Add them to
`/srv/curodav/shared/.env`:

```ini
CC_RADICALE_URL=http://127.0.0.1:5232/<RADICALE_USER>/
CC_RADICALE_USER=<RADICALE_USER>
CC_RADICALE_PASSWORD=<the password you just set>
```

(the app talks to Radicale directly over loopback -- it never needs to go
out through Caddy/TLS for its own sync, only DAVx5 does), then:

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
3. `sudo journalctl -u radicale -f` and `sudo journalctl -u caddy -f` while
   syncing, if it doesn't show up, to see the actual request/auth failure
   rather than guessing.

## Rotating the Radicale password

```bash
sudo ./radicale/install-radicale.sh --reset-password
```

Then update `CC_RADICALE_PASSWORD` in `/srv/curodav/shared/.env`, restart
`curodav`, and update the password saved in DAVx5 on the phone -- all
three (Radicale's own hash, the webapp's env, DAVx5's saved credential)
need to agree, there's no propagation between them.

## Files in this directory

| File                              | Purpose                                             |
|------------------------------------|------------------------------------------------------|
| `deploy.env.example`               | Copy to `deploy.env`, fill in your real domains      |
| `firewall.sh`                      | ufw lockdown: only 22/80/443 open externally         |
| `Caddyfile.template`               | Reverse proxy + TLS for both domains                 |
| `install-caddy.sh`                 | Installs Caddy, renders the template, starts it      |
| `radicale/config.template`         | Production Radicale config (loopback, bcrypt auth)   |
| `radicale/radicale.service`        | systemd unit for Radicale                            |
| `radicale/install-radicale.sh`     | Creates the `radicale` user/venv/service, sets a password |

Nothing here is wired into CI (`.github/workflows/deploy.yml` only ever
runs `curodav-ctl update`) -- this is a one-time setup you run by hand on
the server, not something re-run on every push.
