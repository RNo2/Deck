# Neon setup status

Neon CLI initialization was attempted for organization `org-gentle-leaf-35675420`, project `blue-wave-00466677`, branch `production`, with postgres, auth, ai-gateway, object-storage, functions and realtime selected.

## Prepared locally

- Global npm install failed because the default global directory is unwritable. Use `npx --yes --cache /workspace/.npm-cache neon@latest` instead.
- The local `.neon` context was created and ignored by Git. The CLI explicitly reported an offline, unverified link.
- `neon.ts`, `hello.ts`, root package manifests and dependencies were generated. The function is an unauthenticated generated sample, not an ATLAS backend; secure it before any future deployment.
- Agent plugin installation failed due to an unwritable home cache. The Neon, Postgres, Auth, AI Gateway, Object Storage, Functions and Realtime skills were then installed separately into `.agents/skills` using a writable cache.
- Root `npm run build` forwards to the existing React production build.

## External blockers

Both CLI login and deploy failed with `Could not reach the Neon API`. Direct HTTPS checks to `console.neon.tech` and `oauth2.neon.tech` returned proxy CONNECT HTTP 403. No browser sign-in was launched. Required domain additions (`console.neon.tech`, `oauth2.neon.tech`, `neon.com`) were saved to the environment draft, preserving existing destinations. Saving is not application or publication of network policy.

Apply the required network access through environment settings. Then run in this cloud environment:

```sh
cd /workspace/Deck
npx --yes --cache /workspace/.npm-cache neon@latest login --config-dir /workspace/.neon-cli --no-analytics
```

Complete browser sign-in if requested. The custom config directory is outside the repository; do not copy credentials into chat or Git. Once authentication works, verify the existing project, production branch, supported service region and configuration before resuming `neon deploy`. Secure the generated function before deployment. No service provisioning, account creation or live integration test has succeeded yet, and no `.env.local` or `.env` was downloaded.

## Integration decisions still pending live verification

Keep SQLAlchemy/psycopg for FastAPI; the installed Neon Postgres skill says to preserve an existing ORM/driver. Normal application traffic should use pooled `DATABASE_URL`, while migrations and backups should use direct `DATABASE_URL_UNPOOLED`. The current application migration startup still needs that separation before switching to a pooled Neon URL. No real production schema migration or data copy has been run.

Do not replace ATLAS authentication until Neon Auth is actually provisioned and single-user authorization is enforced. Object Storage, Functions and Realtime need provisioned endpoint/credential bindings and authenticated end-to-end tests. Do not expose server credentials through frontend environment variables. `.env` and `.env.local` remain ignored by Git.

The installed AI Gateway skill says inference requires prepaid credits, including on the Free plan. No card, credits or paid model call is authorized by ATLAS's zero-cost requirement. Provisioning a gateway and receiving endpoint variables would not demonstrate working free inference. Clarify this requirement before testing model calls.

`neon deploy` applies the Neon service policy; the generated sample function does not deploy the existing React/FastAPI application. A separate compatible app host (such as the prepared Render service) is still required unless a later implementation explicitly changes that architecture. No alternative account/project was created to bypass the login failure.
