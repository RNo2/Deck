# ATLAS

Local-first macroeconomic research terminal. Free/open-source software, with no paid API or LLM dependency. This is the foundation phase of the research platform, not the completed institutional research system.

## Run locally

Prerequisites: Python 3.12 and Node.js 22.12+ (Node 24 tested).

Install dependencies first, then configure `ATLAS_USERNAME`, `ATLAS_PASSWORD_HASH` and `APP_ORIGIN` before starting Uvicorn. Generate a hash privately after installing dependencies with `PYTHONPATH=backend .venv/bin/python -m atlas.auth`. See [.env.example](.env.example) for variable names (files are not loaded automatically). Missing login configuration stops startup. SQLite remains the default when `DATABASE_URL` is unset.

```sh
python -m venv .venv
.venv/bin/pip install -r backend/requirements.lock.txt
cd frontend
npm ci --cache ../.npm-cache
cd ..
.venv/bin/uvicorn atlas.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

In another terminal, from `frontend`, run `npm run dev`. Vite proxies `/api` to the backend. For a production bundle use `npm run build`, then `npm run preview`. The backend API has interactive documentation at `/docs` on its local port. Sign in at `/auth/login`. Built frontend files can also be served directly by FastAPI after `npm run build`; set `APP_ORIGIN` to the origin you actually access. The initial app supports one user, with database-backed revocable sessions and CSRF protection.

For prepared Render + Neon configuration, migrations, data transfer and secret setup, see [deployment instructions](docs/deployment.md). No deployment has been performed.

Click **Refresh intelligence** to start a bounded background retrieval of available World Bank and ECB observations. Progress and per-series errors appear immediately and survive browser reloads. See [hosted ingestion workflow](docs/ingestion.md) for budgets, status codes and hosted limitations. No generated or sample financial records are loaded. A network failure is recorded in **Data sources & coverage**. An empty database is an honest empty state, not evidence that macroeconomic conditions are normal.

### Cloud networking

The published cloud environment allows the provider endpoints and official documentation at these HTTPS destinations:

- `api.worldbank.org`, `datahelpdesk.worldbank.org`
- `data-api.ecb.europa.eu`, `data.ecb.europa.eu`

Live ingestion was verified in the published environment: **World Bank: 24 series, 861 observations; ECB: 8 series, 2,400 observations**. Source attribution, analysis, CSV exports, reports and the frontend API proxy also passed verification. Both official documentation endpoints returned HTTP 200. No API keys are required by the selected endpoints.

These counts record the verified ingestion run, not guaranteed future coverage. Future availability is not guaranteed: provider outages, rate limits, API changes, data revisions and environment network policy can affect subsequent refreshes. Check **Data sources & coverage** for the latest status. Mock transport tests validate parsers independently; they do not guarantee external availability.

## Working foundation

- React + TypeScript + Vite terminal, responsive dark interface and Recharts historical chart.
- FastAPI, SQLAlchemy and SQLite; observation vintages retained when values change.
- Provider protocol and World Bank WDI / ECB SDMX adapters, with persisted background progress, per-series/run budgets, isolated provider pipelines, transient-error retries and refresh cooldown.
- Catalog: inflation, real GDP growth and exports/GDP across Brazil, China, India, South Africa, US, Germany, Japan and Mexico; eight EUR reference-rate crosses.
- Per-observation source URL, retrieval timestamp, observation date, unit, geography, currency, frequency and revision-status metadata. Unknown publication dates stay null.
- Trailing z-score, baseline OLS trend, conventional 95% slope interval, sample counts, source-linked tables, CSV export.
- Discovery scans every stored series independently of watchlists. Candidates need |z| ≥ 2 and are explicitly uncorroborated.
- Persistent create/delete watchlists, attributed CSV import, descriptive research note, full JSON report and browser print/PDF.

## Validation

```sh
.venv/bin/pytest -q
cd frontend
npm run build
```

Tests use isolated temporary databases and synthetic **test fixtures only**. Fixtures never populate the application database. They cover invalid/duplicate imports, atomic validation, vintage retention, provenance, provider response parsing, access failures, cooldown, watchlists, empty discovery, zero-variance baselines and exclusion of the latest value from its own baseline.

## Import research data

In **Data sources & coverage**, choose **Import attributed CSV** and provide a unique name, source URL, unit, geography and frequency. UTF-8 CSV must have exactly these headers:

```text
date,value
```

Dates must be ISO `YYYY-MM-DD`; values must be finite numbers. Duplicate dates within a file and future dates are rejected. Null/missing rows should be omitted explicitly, never replaced with zeros. Imports are limited to 10,000 observations and 2 MB of text. Imports are marked user-supplied, not verified. Supply only data you are entitled to use.

## Methodology and boundaries

A latest observation is compared with the preceding 20 daily or 10 other observations (at least eight total records). The baseline uses sample standard deviation and excludes the latest value. Constant baselines yield no z-score. Priority = 60% anomaly strength + 20% history depth + 20% independent corroboration. Corroboration is currently zero, limiting the maximum score to 80. Priority is not a success probability. Direction remains uncertain. These are descriptive level anomalies, not trading signals; FX levels in particular may be nonstationary. Serial dependence and multiple testing limit statistical inference.

World Bank annual observations are represented by year-end dates for their reference year; these are **not release dates**. Requests exclude the current incomplete calendar year. ECB observations are delayed business-day reference rates, not executable quotes. Imported frequency is a user declaration; calendar regularity is not verified. Missing periods are not filled. Current-vintage observations can contain revisions: retrieval vintages are retained from the time ATLAS first sees them, but original publication vintages are unavailable. Do not use these data for point-in-time backtesting.

No policy/news events, supply-demand balance engine, technical indicator suite, cross-market corroboration, matched historical scenarios, scheduled jobs, alerts or comprehensive research reports are implemented yet. Watchlists support saved series combinations and deletion, but editing/organization and saved filter configurations are pending. The architecture is modular, but versioned schema migrations and single-user authentication are implemented, while multi-user authorization and DuckDB/Parquet storage remain future work.

## Data and backup

The backend writes `var/atlas.db` relative to its working directory. Set `ATLAS_DATA_DIR` to relocate it. Keep backend startup in the repository root. Back up with SQLite's online backup API while running:

```sh
.venv/bin/python -c "import sqlite3; a=sqlite3.connect('var/atlas.db'); b=sqlite3.connect('var/atlas-backup.db'); a.backup(b); b.close(); a.close()"
```

Do not copy a database during writes without using the backup API. The application retains data and watchlists, but processes must be restarted in a fresh task. Neither 24/7 uptime nor automatic refresh is promised.

See [architecture and roadmap](docs/architecture.md).
