# Architecture

Magic Tower is a local Docker application exposed at `127.0.0.1:8787`.

```text
Browser → nginx/React web (8787) → FastAPI (internal :8000) → SQLite volume
                                      ↓
                             Microsoft Graph (opt-in, read-only)
                                      ↓
                     local agent clients (loopback API, LOCAL_API_TOKEN)
```

The API owns the durable work queue. `WorkItem` describes a task and `WorkEvidence` preserves the minimum provenance needed to audit an agent's interpretation. Microsoft tokens are stored as AES-GCM ciphertext in the local data volume; access and refresh token values are never returned by the API. A sync refreshes the access token itself, five minutes before its recorded expiry or once when Graph answers 401, and saves the new token encrypted in place of the old one; if Microsoft refuses the refresh token, the sync fails with 409 and the owner reconnects. Inbox reads follow `@odata.nextLink` pages up to the requested limit, and only while the link stays on `https://graph.microsoft.com/v1.0/`, since following it sends the bearer token. A 429 or 503 is retried up to three times, waiting for Graph's `Retry-After` (capped at 30 seconds) or 1, 2 and 4 seconds when it sends none; throttling that outlasts the retries fails the sync with 409.

A background thread in the API process syncs every ready source (Jira once configured, Graph once configured and connected) every `SYNC_INTERVAL_MINUTES`, through the same per-source handlers `POST /api/sync/all` uses. One lock per source keeps a scheduled run and a manual one from overlapping. Each source's last successful sync start is kept in `sync_cursors`; Jira uses it to size its relative `updated >= -<N>m` search window, so no issue updated between two syncs is skipped.

The frontend never receives Microsoft credentials and talks only to same-origin `/api/*`. Nginx proxies API requests to the private Compose network. The browser dashboard is intentionally local-only. Installed agent operations require a distinct `LOCAL_API_TOKEN` Bearer credential; Graph tokens are never made available to an agent. A future non-local deployment needs a separately reviewed browser-auth, CSRF, secret-manager, and database-migration design.

## Boundaries

- **Graph connector:** uses authorization-code PKCE and a one-time encrypted state, calls `/me` only, verifies the configured object ID, requests exactly the three delegated scopes `GRAPH_SCOPES` names in `backend/app/services/oauth.py` (`offline_access`, `User.Read` for the `/me` identity check, `Mail.Read` for the inbox read) and no write scope, normalizes bounded metadata/excerpts, and never decides whether text is work.
- **Agent intake:** receives normalized, redacted source content; produces proposed tasks plus evidence and confidence. A human reviews proposals before any action.
- **Dispatch adapter:** creates a bounded instruction for an installed Codex or Claude Code integration. It does not grant shell, Graph, or mailbox access beyond that integration's own consent.
