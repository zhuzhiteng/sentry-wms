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
Backend: 2946 passed, 55 skipped, 11 warnings in 683.14s
Admin:   30 test files passed, 193 tests passed
Build:   API, workers, dispatcher, and admin images built successfully
Health:  GET /api/health -> {"service":"sentry-wms","status":"ok"}
Admin:   GET / -> HTTP 200
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

The development override avoids production-only webhook SSRF startup guards.
It does not disable authentication, tenant checks, or inventory locking.

## Dependency findings

`npm audit` reports 11 known vulnerabilities in the admin dependency tree:

- 0 critical
- 7 high
- 4 moderate

Direct vulnerable packages include `vite` and `vitest`. Transitive packages
include `brace-expansion`, `browserslist`, `js-yaml`, `source-map-js`,
`undici`, and `zod`.

No automatic dependency upgrade is included in the baseline commit. Dependency
updates must be performed as a separate reviewed change with a full admin build,
unit test run, and browser smoke test.

## Current status

The upstream application builds and its original test suites pass on this
workstation. The shipyard domain has not yet been implemented.
