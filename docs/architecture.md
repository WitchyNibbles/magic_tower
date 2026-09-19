# Architecture

Workboard is a local Docker application exposed at `127.0.0.1:8787`.

```text
Browser → nginx/React web (8787) → FastAPI (internal :8000) → SQLite volume
                                      ↓
                             Microsoft Graph (opt-in, read-only)
                                      ↓
                       Codex / Claude Code intake and dispatch adapters
```

The API owns the durable work queue. `WorkItem` describes a task and `WorkEvidence` preserves the minimum provenance needed to audit an agent's interpretation. Microsoft tokens are stored as AES-GCM ciphertext in the local data volume; access and refresh token values are never returned by the API.

The frontend never receives Microsoft credentials and talks only to same-origin `/api/*`. Nginx proxies API requests to the private Compose network. The browser dashboard is intentionally local-only. Installed agent operations require a distinct `LOCAL_API_TOKEN` Bearer credential; Graph tokens are never made available to an agent. A future non-local deployment needs a separately reviewed browser-auth, CSRF, secret-manager, and database-migration design.

## Boundaries

- **Graph connector:** uses authorization-code PKCE and a one-time encrypted state, calls `/me` only, verifies the configured object ID, reads only the delegated mail scope, normalizes bounded metadata/excerpts, and never decides whether text is work.
- **Agent intake:** receives normalized, redacted source content; produces proposed tasks plus evidence and confidence. A human reviews proposals before any action.
- **Dispatch adapter:** creates a bounded instruction for an installed Codex or Claude Code integration. It does not grant shell, Graph, or mailbox access beyond that integration's own consent.
