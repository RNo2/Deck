# Foundation validation

Validated in the current cloud instance with Python 3.12.14 and Node 24.22.1.

- Backend: 13 tests passed. One third-party Starlette/AnyIO deprecation warning.
- Frontend: strict TypeScript check and Vite production build passed. Build emits an advisory for the 624 kB JavaScript chunk; code splitting is a future optimization.
- Locked Python installation and `npm ci` repeated successfully using a writable workspace npm cache.
- API startup, frontend HTML and frontend-to-backend catalog proxy verified by actual HTTP requests.
- Chromium browser smoke test passed: overview, CSV form import, chart/assessment, discovery, watchlist save/delete, generated report, 390 px mobile layout; no page runtime errors.
- Browser test observations were synthetic test fixtures isolated in `/tmp/atlas-browser-data`, never loaded into the application database. The application database was empty before the subsequent verified live ingestion.
- SQLite online backup command executed successfully.
- After publication with the required domains allowed, live refresh succeeded: **World Bank: 24 series, 861 observations; ECB: 8 series, 2,400 observations**. Both providers reported available. Official documentation endpoints returned HTTP 200.
- Representative World Bank and ECB series passed stored-observation provenance, analysis, CSV export and report checks through the frontend API proxy. Discovery returned four research candidates; these are not corroborated investment recommendations.
- Automated parser tests use controlled mocked responses, separate from live verification. Future availability is not guaranteed; outages, rate limits, API changes, revisions or network policy changes may affect later refreshes. The counts above describe the verified run.

The environment was published with the required provider/documentation domains allowed, and the active policy was verified as enforced. Live ingestion was then verified in the restored environment. Subsequent draft changes are separate from that published version; saving a draft does not apply or publish it.

## Render + Neon preparation validation

- Existing 13 backend tests remain passing. Expanded suite: **23 passed** with a disposable local PostgreSQL 17 server, including authentication, CSRF, session expiry/revocation, Secure cookie flags, login throttling, migration repeatability, legacy SQLite provenance retention, SQLite-to-PostgreSQL transfer, and data/session persistence after engine reinitialization.
- The PostgreSQL integration test is opt-in via `ATLAS_TEST_DATABASE_URL`; it requires an empty disposable database and must never target production. Without that variable, 22 tests run and the PostgreSQL integration test is skipped.
- Strict TypeScript checking and the Vite production build passed. The existing bundle-size advisory and third-party Starlette/AnyIO deprecation warning remain.
- Chromium exercised the built React app served by FastAPI: sign-in, authenticated dashboard and API, sign-out, and revoked access; no browser runtime errors. Test credentials existed only in subprocess environment variables and tests used a separate temporary SQLite database.
- The existing local application database was inspected read-only and retains **3,261 observations**. No live data transfer or cloud database connection was performed.
- No Render deployment, Neon account/database provisioning, Git commit or push was performed. Real hosted TLS, account permissions, free-tier quotas and persistence across a hosted restart still require verification after a separately authorized deployment.
