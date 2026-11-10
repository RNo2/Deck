# Render + Neon deployment preparation

No deployment or external account provisioning has been performed. `render.yaml` describes one **free-plan** Render Python web service that builds React and serves the compiled files from FastAPI. Neon supplies PostgreSQL; no cloud SQLite file or persistent Render disk is used. All authentication, observations, retrieval vintages, provider status and watchlists are database-backed. A Render process restart therefore does not erase them.

## External prerequisites

1. Create your own Render and Neon accounts and select only their free plans. Check current eligibility, quotas, storage/compute allowances, region support and payment requirements before proceeding. No paid plan is required by this repository, but future free availability is not guaranteed. Render free services can sleep; Neon compute can suspend. Cold starts are expected, not 24/7 monitoring.
2. Create a Neon database and select a suitable region near Render. Supply its connection URL through Render's secret environment-variable settings as `DATABASE_URL`. Use `postgresql://` (or `postgres://` / `postgresql+psycopg://`) and set `sslmode=verify-full`; the application defaults to the certifi CA bundle. An explicit `sslrootcert` URL parameter takes precedence, followed by `PGSSLROOTCERT` when set. Preserve other required Neon connection parameters, such as channel binding. Never disable TLS verification. The URL must never be added to Git or a frontend `VITE_*` variable.
3. Set `APP_ORIGIN` to the exact HTTPS origin assigned by Render, e.g. `https://YOUR-SERVICE.onrender.com`, without a path or trailing slash. Set `ATLAS_USERNAME`. Generate a password hash privately using `PYTHONPATH=backend .venv/bin/python -m atlas.auth` and paste the result into the secret variable `ATLAS_PASSWORD_HASH`. Choose a long, unique password. The CLI prompts without echo; do not put passwords or hashes in shell history, tickets or source files. Store credentials securely yourself; no signup, password reset or email service is included.
4. `ATLAS_ENV=production` is already declared in the Blueprint. It requires HTTPS, PostgreSQL and verified database TLS. Missing/invalid authentication configuration stops application startup. No default password or authentication bypass exists.
5. When deployment is separately authorized, make the prepared source available to Render and configure the service using `render.yaml`. No changes have been committed or pushed as part of this preparation. Automatic deploys are disabled in the Blueprint. The build installs pinned Python dependencies, runs `npm ci` and builds React. Startup runs Alembic migrations and starts **one worker** on Render's `$PORT`; the process-local refresh lock requires a single instance/worker. No separate frontend service or CORS configuration is needed.
6. Ensure outbound HTTPS access to the World Bank and ECB endpoints. Existing cloud-environment allowlists are not Render configuration. No data-provider API keys are currently needed.

## Login and session policy

All research APIs, exports, reports, built assets, OpenAPI and documentation require login. Only `/auth/login` and the minimal `/api/health` response are public. Browser forms post to the same origin; unsafe API requests require the `X-ATLAS-CSRF: 1` header and reject mismatched Origin / cross-site fetch metadata. CORS is not enabled.

The password is checked using salted scrypt (N=32768, r=8, p=3). Only the configured hash is read from the environment. Sessions use random 256-bit opaque tokens; only SHA-256 token digests are stored in PostgreSQL. Cookies are HttpOnly, SameSite=Strict, Secure on HTTPS, with an eight-hour absolute expiry. Signing in rotates the current session; signing out deletes it. Changing the configured username or password hash invalidates all existing sessions. Sessions survive app restarts while valid. Response headers prevent caching and framing, and restrict script execution. The research app loads scripts from its own origin; the authenticated API documentation additionally permits its existing jsDelivr assets and nonce-protected initialization.

Login throttling persists across restarts: five failed attempts block the single account until the 15-minute window expires. This deliberately favors a minimal single-user implementation; an attacker who knows the public URL can cause temporary account lockouts. There is no MFA or external identity provider. Keep the URL private where practical and use a strong password. Use Settings → Sign out to revoke the current session.

## Local SQLite development

SQLite remains the default when `DATABASE_URL` is unset. No existing local observations are automatically moved or deleted. Configure `ATLAS_USERNAME`, `ATLAS_PASSWORD_HASH` and `APP_ORIGIN=http://127.0.0.1:5173` in your shell/environment. `.env.example` lists variable names only; ATLAS does not automatically load `.env` files. Start the backend from the repository root and Vite from `frontend`. `/auth` and `/api` are both proxied to FastAPI. For a production-bundle local test, set `APP_ORIGIN=http://127.0.0.1:8000` and access FastAPI directly after building React.

## Schema migrations and existing data

Versioned Alembic migrations are under `backend/migrations`. From the repository root:

```sh
PYTHONPATH=backend .venv/bin/python -m atlas.migrate
```

Migrations also run when the application initializes the database. The first revision adopts the original schema without recreating existing tables; the second adds session/throttling tables. Repeated upgrades are safe. Back up SQLite using the README's online backup command before upgrading a real database. Do not edit an applied migration; add a new revision for future schema changes. Destructive baseline downgrade is deliberately disabled. Use a verified backup for recovery.

A new Neon database starts empty. Re-fetching observations is not equivalent to preserving original retrieval vintages. If you need existing local history, run the utility locally with `ATLAS_ENV` and `RENDER` unset; first back up the source, stop application writers, set `ATLAS_SOURCE_DATABASE_URL` to the SQLite source URL and `DATABASE_URL` to the empty target, then explicitly run:

```sh
PYTHONPATH=backend .venv/bin/python -m atlas.transfer
```

This opt-in utility copies all observation vintages and provenance columns, watchlists and provider status in a target transaction, then resets PostgreSQL ID sequences. It refuses to overwrite nonempty application tables. Login sessions are not transferred. Verify counts, timestamps and sample source URLs before switching databases. No transfer is run by Render startup. Never delete the source until a verified backup and the transfer are confirmed. Provider observations and personal research should remain private.

## Backups and verification

Persistent PostgreSQL storage protects against ordinary service restarts, not accidental deletion or provider/account loss. Arrange and test external PostgreSQL backups (for example, `pg_dump` using environment-supplied connection credentials). Check Neon's current free restore/retention limits; do not assume indefinite backups or unlimited storage.

After a separately authorized deployment, verify: unauthenticated API requests return 401; login redirects to ATLAS; charts and reports load; a watchlist and representative observations survive restart; logout revokes access; and cross-origin writes fail. `/api/health` alone does not validate the authenticated workflow or external providers. Live Render/Neon TLS and account configuration must be checked there; local tests cannot establish hosted readiness.

## Temporary Render network diagnostic

Render's startup command runs `PYTHONPATH=backend python -m atlas.network_diagnostic` before Alembic. It reads only the host/port from `DATABASE_URL` (default port 5432), resolves IPv4 and IPv6 separately, and attempts a TCP connection to each returned address with a three-second connect timeout. A subprocess bounds the complete diagnostic to 25 seconds, including DNS resolution.

Logs contain JSON events tagged `postgres_network`, address families, resolved IP addresses, ports, and sanitized status/error codes. They never contain the URL, username, password, database name, query parameters or raw exception text. The probe performs no database login, SQL, TLS negotiation, data transfer or address substitution. A reachable TCP port does not prove successful TLS or authentication. Diagnostic failures are advisory; migrations retain their existing success/failure behavior.

This diagnostic is temporary. After the next separately authorized deployment, use its Render runtime logs to establish DNS and routing behavior before changing connection configuration. Remove the diagnostic module and its startup invocation once the connectivity issue is resolved. The Blueprint retains `autoDeploy: false`; this diagnostic runs no deployment commands.

## Render login configuration diagnostics

The required variable names are exactly `ATLAS_USERNAME` and `ATLAS_PASSWORD_HASH`. Set their values in Render's **atlas → Environment** settings. Paste only the username and complete hash in the value fields: no shell assignment (`export ...` / `ATLAS_PASSWORD_HASH=...`), surrounding quotes, code fences, or prompt text. Do not put the plaintext password in an environment variable or build/start command.

The hash format is exactly `scrypt$<standard-Base64 salt>$<standard-Base64 digest>`: the salt must decode to 16 bytes and the digest to 64 bytes. The generator/verifier use UTF-8 and scrypt N=32768, r=8, p=3, dklen=64. Matching those parameters alone is insufficient if a separate generator emits hex, a different salt size, or a different serialization. The existing local generator produces the required format without needing any credential changes elsewhere.

Surrounding whitespace in the configured username and hash is normalized; passwords themselves are never trimmed. Quoted or malformed hashes remain rejected. Startup now reports fixed, value-free reasons naming the failed variable, such as `ATLAS_USERNAME: missing`, `ATLAS_PASSWORD_HASH: surrounding_quotes_remove_quotes`, `salt_invalid_standard_base64`, or `digest_must_decode_to_64_bytes`. Neither username values, hashes, decoded bytes nor passwords are logged. The old combined error could not distinguish these causes, so it alone does not establish what was entered in Render.

After deploying this fix separately: save the exact variables for the **atlas** service and select Render's **Save, rebuild, and deploy** option (or save and manually deploy the latest `work` commit). Confirm the deployed commit is the intended one. If startup still rejects configuration, its sanitized reason identifies the field to correct; never paste the values or a complete environment dump into logs or support messages. Keep the existing `DATABASE_URL`, TLS and network settings unchanged. Once healthy, sign in with the configured username and the original password, then verify an authenticated research page loads. No login credential is regenerated automatically by a deploy.
