# Admin-ever

Administrator backend for the desktop application. A Django + Django REST
Framework JSON API that manages clients, partners, users, contracts and
headquarters, and authenticates desktop-app users, returning the roles that
authorize them inside the app. The product UI is a custom frontend built
against this API; the Django admin at `/admin/` is kept only as a staff-side
escape hatch for data inspection.

## Domain model

```
Partner ──M:N── Client          a partner's users administer its linked clients
Client  ──1:N── Contract        contracts gate access; expiry revokes it
Client  ──1:N── Headquarters ── M:N ── User (assignments, same-client enforced)
Client  ──1:N── User (CLIENT type)
Partner ──1:N── User (PARTNER type)
User    ──M:N── Role            role codes are returned on login / in JWT claims
```

Three user populations, one `User` model (`accounts.User`, `user_type` field):

- **PLATFORM** — your staff; no client/partner FK; scope = all clients.
  Tiers are roles: `SUPER_ADMIN`, `PLATFORM_SUPPORT`, `PLATFORM_VIEWER`.
- **PARTNER** — belongs to a `Partner`; scope = the partner's linked clients.
- **CLIENT** — belongs to a `Client`; scope = that client only.

Authorization always has two axes: **roles** say what a user may do,
**scope** says which clients they may do it to. Scope has a single source of
truth: `Client.objects.visible_to(user)` (`organizations/models.py`) — every
future endpoint must filter through it.

## Contract-based revocation

- `User.has_active_access()` is checked at **login and token refresh**. A
  client user whose client has no currently-valid contract gets a 401 with
  code `access_revoked`. Access tokens live 30 minutes, so revocation takes
  effect within one token lifetime — no blocklist needed.
- Partner/platform users are never locked out by a client's expiry; the
  lapsed client silently drops out of `user.scoped_clients()` instead.
- A nightly job keeps stored statuses honest:
  `python manage.py expire_contracts` (run via cron or Celery Beat).

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/auth/login/` | Credentials → access + refresh JWT. Access token carries `user_type` and `roles` claims. |
| `POST /api/v1/auth/refresh/` | Refresh → new tokens; re-checks contract validity. |
| `GET /api/v1/me/` | Identity, roles, client/partner, `scoped_client_ids`, headquarters. |
| `GET /api/docs/` | Swagger UI (OpenAPI schema at `/api/schema/`). |

## Getting started

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # adjust SECRET_KEY etc.
docker compose up -d db         # PostgreSQL 16 (or omit DATABASE_URL for SQLite)
python manage.py migrate        # also seeds the six well-known roles
python manage.py createsuperuser
python manage.py runserver
```

Run the tests:

```bash
python manage.py test
```

## Project layout

- `accounts/` — custom `User`, `Role`, auth API (`accounts/api.py`)
- `organizations/` — `Client`, `Partner`, `Headquarters` + assignments, scoping
- `contracts/` — `Contract`, validity querysets, `expire_contracts` command
- `config/` — settings (env-driven via `django-environ`), URLs

## Roadmap

- [x] Phase 1 — foundation: custom user, JWT auth, PostgreSQL, OpenAPI, CORS
- [x] Phase 2 — domain models with scoping + contract validity (tested)
- [x] Phase 3 — auth API: login/refresh with contract checks, `/api/v1/me/`
- [ ] Phase 4 — admin CRUD API: clients, partners, users, contracts, headquarters
- [ ] Phase 5 — custom admin UI against the OpenAPI schema
- [ ] Phase 6 — lifecycle & hardening: audit log, login rate limiting, nightly job wiring
- [ ] Phase 7 — deployment & CI
