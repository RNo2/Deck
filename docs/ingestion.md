# Bounded hosted ingestion — first milestone

## Diagnosis and scope

The previous refresh handler fetched all 32 series inside the initiating HTTP request and wrote each provider's status only after that provider's entire loop finished. A long-running request, process interruption, or a disconnect before provider status was committed could leave coverage at zero / “not checked” without useful progress. The UI had no status polling. This code-level failure path was reproduced and corrected; the specific provider response from the hosted incident was not available for verification here.

The new workflow retrieves free, keyless World Bank and ECB data for the existing catalog. CSV remains supplementary, never a prerequisite for these integrations. This milestone does not add arbitrary instrument search, price providers, technical/fundamental engines, paid APIs or LLM calls.

## Contract

- Authenticated, CSRF-protected `POST /api/refresh` commits a durable job and initial provider status, returns **202**, then starts work outside the request lifetime.
- Authenticated `GET /api/refresh` returns the latest job ID, status, timestamps/deadline, counts, and per-series outcomes/errors. It survives browser reloads. The frontend polls every two seconds while active, refreshes coverage, and updates research/discovery when finished. Temporary polling failures are visible; after bounded retries the UI reports unknown status rather than claiming success.
- The default request scans the entire configured catalog. An optional JSON body `{"series_ids":["ecb:USD"]}` reuses the same ingestion service for a subset. Only known catalog IDs are accepted; no arbitrary provider URLs are exposed. This is the foundation for future automatic on-demand retrieval, not a new instrument-search engine.
- An active run is returned to duplicate callers rather than launching competing work. This also means a different requested subset is not appended to an active run; inspect the returned series list and retry after completion/cooldown if necessary.
- Admission control persists in the database. A five-minute interval between run starts returns 429 with `Retry-After`; the UI displays the retry interval.

## Work bounds and provider isolation

There are at most two provider pipelines, each fetching its series sequentially with a short spacing delay. Each series has a 20-second async budget; HTTP connect/read timeouts are five/eight seconds. A full run has a 120-second budget. Transient HTTP retries retain exponential backoff, honor `Retry-After`, and avoid retrying before a long provider-requested cooldown. A 401, 403, 429 or proxy rejection stops the affected provider's remaining requests; the other provider can still succeed. Remaining series are explicitly skipped or failed rather than silently counted as successful.

Database work runs outside the event loop. Latest-vintage lookups are batched instead of querying once per observation, reducing hosted database round trips. Short transactions atomically persist a valid series and its progress. PostgreSQL row locks and local SQLite serialization prevent lost progress; job IDs fence late results from superseded runs. SQL connectivity/commit latency still depends on the database and host; a provider budget is not a guarantee against a stalled external database operation.

## Integrity, errors and recovery

Migration `0003` adds one durable ingestion status row; existing observation tables and all their vintages remain intact. Complete batches are validated before storage: supported series/metadata, finite values, valid nonfuture dates, unique dates, trusted source host and retrieval timestamp. Failed validation or persistence cannot partially overwrite that series. Successful earlier series remain available if another source fails. Repeated identical observations are deduplicated; revisions retain their original provenance and retrieval vintages.

Status/error codes are sanitized, including `timeout`, `http_403`, `http_429`, `proxy_connection_failed`, `connection_failed_dns_tls_or_network`, `invalid_or_empty_provider_data` and `storage_write_failed`. These do not expose raw exception bodies or secrets. A transport code is not proof of a specific DNS/TLS root cause. Coverage shows attempt status separately from observation date and last retrieval time.

Graceful shutdown cancels outstanding requests and finalizes progress. On startup, unfinished jobs become interrupted; stale deadlines are also recovered when status is read. Existing observations are retained. Background execution is **not** durable across Render suspension or process termination: this dependency-free design uses one web process, not a separately provisioned queue/worker. Interrupted work is reported, not silently retried or falsely marked complete. A later refresh can retry after cooldown.

## Hosted limitations and verification

Keep one Uvicorn worker and one service instance, as configured in `render.yaml`. Free Render sleeping/restarts, Neon availability/quotas and upstream rate limits or access restrictions remain external constraints. No 24/7 automation or guaranteed free-provider availability is claimed. No paid infrastructure was introduced.

No hosted deployment or live provider request was performed for this change. After a separately authorized deployment, check the job's per-series results and the source coverage page. An HTTP 202 means accepted, not ingested. Verify successful terminal outcomes, stored observation counts, source URLs and retrieval dates. Provider-denied access will now be visible without requiring CSV or fabricated records. Existing temporary startup network diagnostics remain unchanged.

Tests cover authenticated background admission, HTTP provider parsing through storage, progress and reload visibility, duplicate prevention, cooldowns, provider isolation, deadlines, shutdown/restart recovery, atomic rollback, invalid batches, deduplication/revisions and batched storage. PostgreSQL checks use a disposable local database; browser checks use isolated synthetic provider fixtures, never the application database.
