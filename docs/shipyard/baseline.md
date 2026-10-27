# Shipyard WMS Baseline

## Upstream baseline

- Repository: `https://github.com/hightower-systems/sentry-wms`
- Release tag: `v1.37.0`
- Resolved commit: `9eac4653f6a74fc0631492cdbca23a0e8a45f3dd`
- Internal branch: `codex/feat-shipyard-domain-20261027`
- License: Apache-2.0

The upstream repository remains the `origin` remote. This project does not push
to upstream.

## Open upstream work at intake

At baseline time, the upstream repository had two open pull requests:

- `#463`: sidebar permission filtering
- `#464`: draft operation identities and allocation evidence

Neither pull request is part of the baseline. Do not merge a draft or unreviewed
upstream branch without a separate compatibility review.

## Local environment

- Docker Engine: `29.8.0`
- Docker Compose: `v5.5.1`
- API: Flask 3.1.3 / Python 3.11
- Database: PostgreSQL 16
- Admin: React 19 / Vite 8

The development host already reserved TCP `5432`, so the ignored local
`docker-compose.override.yml` maps PostgreSQL to `127.0.0.1:55432`. Container
networking still uses `db:5432`.

Runtime secrets are generated in-process for local verification and are not
written to the repository.

## Windows checkout fix

The host Git configuration used `core.autocrlf=true`, which checked shell
scripts out with CRLF line endings. PostgreSQL's Linux entrypoint then failed
with:

```text
/docker-entrypoint-initdb.d/02-seed.sh: cannot execute: required file not found
```

The repository now contains a minimal `.gitattributes` rule requiring LF for
all shell scripts. This change is required for Docker Compose to work on
Windows.

## Verification

Commands use a dedicated `sentry_test` database.

```text
Backend: 3043 passed, 55 skipped, 11 warnings
Admin:   32 test files passed, 203 tests passed
Miniprogram: 17 tests passed
Admin build: production build passed
Schema:  087 applied twice to test; fresh db/schema.sql created
HTTP E2E: passed (two-pallet OCR receipt → whole-ticket outbound → LOADED)
```

The API test command must override the container's production environment:

```powershell
docker compose exec -T `
  -e TEST_DATABASE_URL=$testDbUrl `
  -e FLASK_ENV=development `
  -e SENTRY_ALLOW_INTERNAL_WEBHOOKS=false `
  -e SENTRY_ALLOW_HTTP_WEBHOOKS=false `
  api python -m pytest tests/ -q
```

The standalone HTTP E2E uses the same isolated `sentry_test` database and
restores its seed data after the run:

```powershell
docker compose exec -T `
  -e TEST_DATABASE_URL=$testDbUrl `
  api python tests/e2e_shipyard_http.py
```

It starts a loopback Flask server, then performs login, binding/zone setup,
inbound manifest confirmation, two OCR receipts, formal-outbound confirmation,
two OCR scans with a missing-suffix recovery, stock depletion, loading
confirmation, refreshed backend reads and photo-byte verification. OCR is a
deterministic test stub because CI has no public-cloud credentials.

The development override avoids production-only webhook SSRF startup guards.
It does not disable authentication, tenant checks, or inventory locking.

## Dependency findings

The shipyard dependency review upgraded Vite to 8.3.5, Vitest to 4.1.12,
PyJWT to 2.15.0, and refreshed the remaining locked transitive packages.

- `pip-audit`: no known vulnerabilities;
- `npm audit`: 0 vulnerabilities;
- admin test suite: 32 files and 200 tests passed;
- admin production build: passed;
- the files touched by the shipyard outbound slice pass ESLint; the repository
  still carries pre-existing lint debt outside this slice.

The admin lint debt is not introduced by the shipyard domain and must not be
described as clean until it is reduced and re-verified.

## Current status

The upstream application builds and its original test suites pass on this
workstation. The first shipyard slice is implemented: temporal project/zone
configuration, fixed-template inbound manifest parsing, source-file retention,
binding enforcement, manifest void/reimport, and one cargo ticket per source
row.

The second slice is implemented as a separate ticket-level stock ledger:
photo-based label OCR, server-side field validation, per-pallet photo evidence,
actual quantity receipt, shortage reporting, replenishment and idempotent
confirmation. QR input remains only as a legacy compatibility path and is not
used by the current mini-program workflow.

The third slice adds shipyard distribution-demand Excel recognition,
warehouse-scoped dispatch matching, source-line lineage and printable front
warehouse delivery notes. `085_shipyard_outbound_documents.sql` is idempotent
and the consolidated `db/schema.sql` contains the same final structures.
The React admin now exposes `/shipyard-outbound` for import review, match
resolution, delivery-note generation and printing.

Shipyard role templates now cover manager, receiver, outbound operator and
read-only auditor, with development-only virtual user seeding. The React admin
exposes `/shipyard-settings` for ship/project bindings and zone-to-ship
placement rules.

The fourth shipyard slice adds formal outbound-manifest recognition, exact
material-code/item/spec stock matching, whole-ticket multi-label photo OCR,
per-pallet outbound photo evidence, one-time stock depletion, loading
confirmation and a native WeChat mini-program for receiving and outbound work.
Migration `086_shipyard_formal_outbound.sql` is idempotent and the consolidated
schema contains the same structures. Generic Sentry `items` / `inventory`
synchronization remains deferred until the shipyard material-code mapping is
agreed.
