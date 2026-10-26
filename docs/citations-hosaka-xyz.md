# citations.hosaka.xyz — hosted scaffold

Status: **scaffold only**. Local deployment at `http://localhost:8069/citations`
is the supported path today. This document fixes the shape of the hosted
deployment so the local code does not need to be rewritten later.

## Shape

```
browser ──https──▶ citations.hosaka.xyz (reverse proxy, TLS)
                        │
                        ▼
                 VirgoZone (uvicorn, CITATIONS_* only, media/chat disabled)
                        │  stdlib `citations` package, own SQLite replica
                        ▼
                 Supabase hosaka_citations schema (publishable key + user session)
```

- Same VirgoZone image, same `/citations` page and `/api/citations/*` routes.
  The feed/chat/schedule panels are irrelevant on the public host and are hidden
  by serving only `/citations` through the proxy (`location = / { return 302 /citations; }`).
- `hosaka.xyz` (Next.js on Vercel) links to `citations.hosaka.xyz`; nothing from
  the citations stack runs on Vercel. Vercel functions are stateless and the
  extension needs a persistent SQLite replica plus a long-lived sync loop.
- The hosted VirgoZone is just another sync device for the shared workspace,
  exactly like the organizer's laptop. Conflicts are preserved and surfaced in
  the same Conflicts dialog.

## Auth gate (required before exposing anything)

Reads must be gated too: offender names are personal data for the party.

1. **Proxy-level gate for the whole host.** Cloudflare Access / oauth2-proxy /
   Tailscale Funnel with identity, allow-listing the organizer group. This is
   the first milestone; no application change is required.
2. **Application organizer mode.** Today: the shared VirgoZone admin cookie.
   Hosted: replace `ADMIN_PASSWORD` with Supabase Auth sign-in — the organizer
   logs in with their own workspace email; VirgoZone checks `hc_is_member` via
   the user's JWT, then sets the organizer cookie. Mutations keep flowing through
   `POST /api/citations/actions`, so only `app/routes/admin.py` changes.
3. **Public read tier (optional).** If the wall should be open, add a
   `CITATIONS_PUBLIC_FIELDS` allow-list that strips description/actor/notes and
   shows first name + violation + status only.

## Config

| Env | Hosted value |
| --- | --- |
| `VIRGOZONE_HOST` | `127.0.0.1` (proxy in front) |
| `VIRGOZONE_PORT` | `8069` |
| `CITATIONS_SOURCE` | path to the `hosaka_citations` checkout in the image |
| `CITATIONS_SUPABASE_URL` / `CITATIONS_PUBLISHABLE_KEY` / `CITATIONS_WORKSPACE_ID` | from the handoff; publishable key only |
| `CITATIONS_SYNC_ENABLED` | `true` |
| `CITATIONS_PUBLIC_WRITE` | `false` |
| `ADMIN_PASSWORD` | unset once Supabase Auth sign-in lands |

Secrets stay in the host's secret store (systemd `LoadCredential=` or the
platform's secret manager). Never a service-role/secret key, never the
organizer password on disk — sign in once with `python -m app.citations_login`
on the host, which stores only the refreshable session (0600).

## Vercel account facts (read 2026-10-25, `vercel` CLI 65.2.0)

- Team `barkbarkbarkbarkbarkbarkbarks-projects` (hobby). `hosaka.xyz` is a
  third-party-registered domain attached to this team; nameservers are not
  Vercel's, so `citations.hosaka.xyz` needs a CNAME/A record at the registrar
  (or `vercel dns add` if the zone is moved to Vercel).
- Existing projects on the domain: `cyber-deck` → `www.hosaka.xyz`,
  `hosaka-web` → `terminal.hosaka.xyz`, `hosaka-install` → `install.hosaka.xyz`.
- Vercel cannot run this VirgoZone process (persistent SQLite + sync loop +
  WebSockets). The Vercel role for `citations.hosaka.xyz` is one of:
  1. **DNS only** — point `citations.hosaka.xyz` straight at the VirgoZone host
     (Tailscale Funnel / Cloudflare Tunnel / VPS). Simplest; nothing deployed on Vercel.
  2. **Edge gate + rewrite** — a tiny Vercel project (`citations-gate`) that owns
     the subdomain, enforces the identity gate (Vercel's password/SSO protection
     or a middleware OAuth check), and `rewrites` `/:path*` to the VirgoZone origin.
     WebSockets are not proxied by Vercel rewrites, so the page would fall back to
     its 60-second poll; everything else works.
  Milestone 1 should be route 1 behind an identity-aware tunnel; route 2 is the
  fallback if a Vercel-managed gate is preferred.

## Route 2 status (2026-10-25)

Deployed. Project `citations-gate` (`/home/marc/Documents/codespace/citations-gate`,
Next.js 16 Edge proxy) is live at `https://citations-gate.vercel.app` with
`GATE_SECRET`, `GATE_ACCESS_CODE`, `CITATIONS_GATE_TOKEN` set as sensitive
production env. `citations.hosaka.xyz` is attached to the project and verified;
it resolves once GoDaddy has:

```
Type   Name        Value
CNAME  citations   65715a82154f06de.vercel-dns-017.com.
```

The public wall does not rewrite to this machine. After the access code,
`/api/wall` reads `hosaka_citations` with a member session stored on Vercel
(`SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_WORKSPACE_ID`,
`SUPABASE_REFRESH_TOKEN`). That refresh token is a second login, not the copy
in `data/citations/supabase-auth.json` — sharing one token lets rotation log
both sides out. Local VirgoZone keeps syncing into the same workspace.
`CITATIONS_ORIGIN` is unused. Tailscale Funnel is not on the page's request path.

## Deployment checklist

- [ ] Container/VM with Python 3.12, this repo, and `hosaka_citations` checked out
- [ ] Persistent volume for `DATA_DIR/citations/` (replica + session)
- [ ] `python -m app.citations_login` run once on the host
- [ ] Reverse proxy with TLS, `/` → `/citations`, WebSocket upgrade for `/ws`
- [ ] Identity gate (milestone 1) in front of the proxy
- [ ] DNS `citations.hosaka.xyz` → proxy; link from hosaka.xyz
- [ ] Health: `GET /api/citations/status` → `available: true`, `last_error: null`
- [ ] Hosaka-side: optional `virgo-zone` plugin pointed at a loopback tunnel
