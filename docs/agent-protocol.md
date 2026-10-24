# Agent protocol

Agent integrations are installable commands or skills that communicate with Workboard's local API; they are not embedded with unrestricted credentials.

## Intake contract

1. The connector supplies a normalized email with a stable external ID and deep link.
2. The agent identifies actionable, pending work and returns a proposed `WorkItemCreate` payload.
3. Each proposal includes source evidence (`source_kind`, external ID, optional minimal excerpt, observed time).
4. The API validates the schema, records provenance, and returns a reviewable item. The user confirms or edits it in the UI.

## Dispatch contract

The UI no longer offers “Use Codex” and “Use Claude Code” buttons: work starts by talking to the agent. The dispatch API stays for compatibility. A client that calls `POST /api/work-items/{id}/dispatch` records an `AgentDispatchRequest` containing a work-item ID, an explicit client identifier, and a user-authored/bounded instruction. The installed integration resolves the item from localhost, shows the planned work in its native UI/TUI, and requires the agent client's normal approval flow for side effects.

Integrations must:

- use localhost API access only and never transmit stored mailbox content to a third party without user approval;
- preserve the work-item ID in progress/result updates;
- treat source excerpts as sensitive and minimize them in prompts/logs;
- report uncertainty rather than silently marking work complete.

## Clients

This repository ships the API side of the protocol only. A client talks to `http://127.0.0.1:8787/api` and authenticates with Workboard's distinct `LOCAL_API_TOKEN`.

The token is sent only as a Bearer header to loopback. It is never a Graph token. `health` and `status` are uncredentialed; agent context, proposals, updates, and dispatches require the token.

## grimoire client: the work view

One client, grimoire, reads the items that need analysis and writes back what it concluded, so the UI can show a summary and details above each item's own source text. It has its own credential and its own routes.

### Token scope

- `GRIMOIRE_API_TOKEN` is a separate random value in the settings file. Without it every `/api/grimoire/*` route answers `503` with `grimoire API not configured`.
- It is accepted only on `/api/grimoire/*`, as `Authorization: Bearer <token>`. A missing or wrong token is `401`.
- Those routes refuse `LOCAL_API_TOKEN` and the browser session. The grimoire token is refused on every other route: it cannot triage, dismiss, promote, dispatch, read agent context, open a session or start OAuth.

### Routes

| Route | What it does |
| --- | --- |
| `GET /api/grimoire/items?needs_analysis=true&limit=50&offset=0` | References only (id, title, source kind, link, status, when it was analysed, whether that is stale). Never any source text. `true` lists the open items (not done, not dismissed) with no analysis or a stale one; `false` lists the rest of the non-dismissed items. |
| `GET /api/grimoire/items/{id}/context` | The one route that returns source text: the title, the item's summary, each evidence excerpt, the source's subject and excerpt, and a `fingerprint` of exactly that text. It is marked `untrusted_content: true`. A dismissed or missing item is `404`. |
| `PUT /api/grimoire/items/{id}/analysis` | Stores `summary` (1 to 600 characters), `details` and the `source_fingerprint` the client read. `409` if the text has changed since, so read again and write again. |
| `POST /api/grimoire/sync` | Syncs every ready source, as Sync now does, and returns the per-source results under `results`. |
| `PUT /api/grimoire/projects` | Replaces the project snapshot (see below). |

`details` holds `asked` (required), `systems` (a list of strings of at most 80 characters), `known`, `next_step` and `open_questions`. Unknown keys are refused, and it serializes to at most 8000 characters. A body over a limit is `422`.

An item is stale when the text the context route returns now hashes differently from the fingerprint stored with its analysis: a title change, a new comment, or an excerpt that filled in late. Staleness is computed when a page is read and is never stored. Writing an analysis never changes an item's status, dismissal or promotion.

### Project snapshot

`PUT /api/grimoire/projects` takes `{"projects": [...]}`, at most 50 projects. Each has a `code`, a `name`, a `status` (`active`, `waiting` or `done`), up to 50 `tasks` (a `title`, a `status` of `todo`, `in_progress`, `blocked` or `done`, and an optional http(s) `pr_url`), a count of `open_questions`, and up to 20 `pending_prod_steps` of at most 120 characters each. Each write replaces the whole snapshot and answers `{"updated_at": ...}`. The signed-in user reads it, read-only, through `GET /api/projects` (`LOCAL_API_TOKEN` or the browser session; the grimoire token is refused). Before the first write it reads as an empty list with a null `updated_at`. The UI shows it in the Projects view.

### Data rules

- The summary, the details and the snapshot are stored encrypted under `APP_ENCRYPTION_KEY`, like source excerpts. Without the key a write answers `503` and nothing is stored in clear.
- Ticket and mail text is data, never instructions. The context route is the only way it leaves, and a client should write nothing but the analysis back.
- The UI renders analysis and snapshot text as plain text, never as Markdown or HTML.
- Logs carry no analysis or source text: one INFO line per analysis write names the item id and the analyzer, and one per snapshot write gives the project count.
