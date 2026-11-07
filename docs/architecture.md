# Architecture and phased delivery

## Foundation

Browser → Vite `/api` proxy → FastAPI → provider adapters / analytics → SQLAlchemy → SQLite locally / PostgreSQL via `DATABASE_URL`.

- `backend/atlas/catalog.py`: available universe and source capability metadata.
- `providers.py`: provider protocol, request retry policy, parsing and normalization.
- `storage.py`: durable observations, retrieval vintages, provider status, watchlists and database-backed login sessions.
- `auth.py`: single-user scrypt login, opaque sessions, CSRF checks and durable throttling.
- `migrate.py` / `backend/migrations`: Alembic schema upgrades preserving existing SQLite data.
- `transfer.py`: opt-in, transaction-protected data transfer into an empty target, preserving every observation vintage.
- `analysis.py`: trailing-only statistics and transparent priority decomposition.
- `main.py`: orchestration, data validation and API. Refresh performs bounded sequential requests, records failures and retains existing observations.
- `frontend/src/main.tsx`: research workflows, data coverage, chart, discovery and local reports.

Python and Node toolchains and all selected libraries are free/open-source. Live ingestion was verified for World Bank (24 series, 861 observations) and ECB (8 series, 2,400 observations). These counts describe the verified run; future availability is not guaranteed. Source terms, coverage and freshness must still be assessed for each research use. World Bank and ECB adapters are selected for public, keyless endpoints; neither provides real-time trading quotes.

## Next phases

1. Reverify live sources after network or provider changes. Add provider contract integration tests, explicit ingestion-run tables per series, configurable rate limits and additional schema revisions.
2. Add validated return-based technical indicators, statistical diagnostics, frequency-aware alignment and fundamental balance calculations. Add DuckDB/Parquet when data volumes justify it.
3. Add independently sourced fundamentals/policy events, publication/effective-date distinction, relationship graph, configurable weights, multiple-testing controls and corroborated discovery. Avoid double counting correlated evidence.
4. Expand country/asset catalogs through provider capabilities, saved research filters, editable watchlists and contextual multi-entity analysis.
5. Add persisted report snapshots, complete printable evidence tables/charts, scheduler with durable job status, configurable in-app alerts and reliable backups.
6. Add point-in-time historical vintages where available, walk-forward/out-of-sample evaluation with cost assumptions, optional local ML and multi-user authorization.

Each phase must preserve a runnable product, include analytical tests and functional validation, and identify missing evidence explicitly. No paid AI infrastructure is required.

## Deployment preparation

`render.yaml` builds React and serves it from FastAPI on one free-plan Render service. Neon PostgreSQL stores application data and sessions; the ephemeral Render filesystem is not used for cloud persistence. Authentication is required in local and production modes. Deployment prerequisites, backup limitations and credential handling are documented in [deployment.md](deployment.md). No external resources have been created.
