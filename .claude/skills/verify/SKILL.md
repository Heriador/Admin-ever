---
name: verify
description: Build, launch and drive the Admin-ever Django API to verify changes at its HTTP surface.
---

# Verifying Admin-ever

The surface is the JSON API. Verify by launching the dev server and
driving endpoints with curl — not by running the test suite.

## Launch

```bash
pip install -r requirements.txt          # if deps missing
python3 manage.py migrate                # SQLite fallback needs no .env
python3 manage.py runserver 127.0.0.1:8765 &   # background it
curl -s http://127.0.0.1:8765/api/schema/     # readiness probe (200)
```

## Seed data fast

The test factories work in `manage.py shell` and handle FK wiring:

```python
from accounts.models import Role, UserType
from accounts.tests.factories import *
acme = make_client('Acme'); make_contract(acme)
make_user(client=acme, username='alice', roles=[Role.Codes.CLIENT_ADMIN])
```

Factory password is `test-password-123`.

## Flows worth driving

- `POST /api/v1/auth/login/` — valid creds → tokens; decode the access
  token (`jwt.decode(..., options={'verify_signature': False})`) and
  check `user_type` + `roles` claims.
- Expired/absent contract for a CLIENT user → login and refresh must
  both return 401 with `access_revoked`.
- `GET /api/v1/me/` with Bearer token — check `scoped_client_ids`
  excludes clients without a valid contract (partner users especially).
- `python3 manage.py expire_contracts` — flips overdue ACTIVE contracts,
  warns about clients losing access.

## Gotchas

- **The dev machine's `.env` points at the user's local PostgreSQL**
  (`DATABASE_URL=postgres://...`), so `manage.py migrate`/`shell` touch a
  persistent DB, not a scratch SQLite file. Seed with unique names
  (factory sequences restart per process → `C-0` collisions), track every
  row you create, and delete exactly those rows when done.
- On Windows/PowerShell 7: use `Invoke-WebRequest -SkipHttpErrorCheck`
  to read 4xx bodies; 204 responses have byte-array content (skip
  `.Substring`). Launch server via
  `Start-Process python -ArgumentList "manage.py","runserver","127.0.0.1:8765","--noreload" -WindowStyle Hidden`.
- Wrong-password and unknown-user intentionally share one 401 message
  (no user enumeration); contract expiry has a distinct 401 message.
- Write-capability denials are 403 even where plain DRF would give 405
  (permission check runs before handler resolution).
