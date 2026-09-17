# Explore — the GUI, and what actually stands between it and the product

## Idea
Tasks from email, Jira and chat, analyzed by an agent, cleaned/grouped/organized, shown in a web
GUI where the owner browses them and hands them to coding agents. Owner believes only an API exists.

## Facts
- **A real frontend already exists and builds.** React 19 + Vite + TS, 12 files.
  `npm install && npm run build` → exit 0, 252ms, `dist/assets/index-BOyRqVLT.js 230.56 kB`.
  Not a scaffold: `frontend/src/main.tsx` (31 dense lines, 11 KB) renders queue list, status/source
  filters, search, evidence blockquotes, agent-handoff panel, settings modal; 7.4 KB hand-written
  CSS. It calls `/api/session`, `/api/work-items`, `/api/sync`, `/api/work-items/{id}/dispatch`
  (`frontend/src/api.ts:21-42`). It **falls back to demo data on 401/503** (`main.tsx:6-10,17`),
  which is why it can look unwired.
- Served same-origin: nginx proxies `/api/` → `api:8000` (`frontend/nginx.conf:11`), strict CSP
  (`nginx.conf:10`), loopback-only port (`docker-compose.yml:35`). 28 API routes, all under `/api`.
- **The missing link is Source → WorkItem.** Graph sync is real — OAuth+PKCE, encrypted token store,
  inbox+chat fetch, normalize, dedupe, idempotent persist (`backend/app/services/sync.py:35-50`,
  `integrations/graph.py:41-58`). But `persist_signals` writes **only `Source` rows**
  (`backend/app/services/graph.py:45`). The only code constructing a `WorkItem` is
  `create_work_item` (`services/work_items.py:42`), reachable only via `POST /api/work-items` or
  `POST /api/agent/proposals`. **Sync an inbox and the queue stays empty.**
- **No LLM anywhere.** Grep for anthropic/openai/llm/gpt across `.py/.ts/.tsx/.toml` hits only the
  literal client ids `"codex"|"claude-code"`. The "analyzed by an agent" step does not exist.
- **Dispatch is only a DB row.** `create_dispatch` inserts and stops (`services/work_items.py:125-131`);
  zero `subprocess`/`Popen` in the repo. The UI's handoff button copies
  `scripts/pending-work context <id>` to the clipboard (`main.tsx:29`). Agents *pull* via
  `scripts/pending-work` (205 lines, loopback-only, `PENDING_WORK_API_TOKEN`).
- **Jira and Slack do not exist** — no code, no config keys. `source_kind` is only
  `outlook_email | teams_message | manual` (`models.py:25-28`). Jira Cloud would be email+API token
  or 3LO (`/rest/api/2/search` is gone, use `/search/jql`); Slack needs a user token `xoxp` with
  `channels:history`/`im:history`.
- Graph is delegated-only, scopes `offline_access User.Read Mail.Read Chat.Read`
  (`services/oauth.py:19`); five settings must be present or sync 409s (`config.py:51`); sign-in is
  rejected unless `/me.id` equals the target user (`services/sync.py:46`). Many tenants force admin
  consent for `Chat.Read`.
- **Security/scale debt that a real GUI would expose:**
  - Mail/Teams excerpts up to 2000 chars sit in **plaintext SQLite** (`services/graph.py:50`); only
    the token and OAuth-state files are AES-GCM encrypted (`services/crypto.py:34`).
  - Sessions are a **process-local dict** (`security.py:31`) — any API restart logs the browser out.
  - **No index anywhere** in `models.py`; `GET /api/work-items` and `/api/sources` return every row
    unpaginated (`api/routes.py:66`). Only `POST /api/sync` is bounded (limit ≤ 100).
  - `GET /api/sync/status` has **no auth dependency** (`api/sync.py:14`).
  - No Alembic: startup does `create_all` + a hand-written `ALTER TABLE` (`main.py:46`).
  - Frontend deps are all `"latest"` with the lockfile **untracked**, and `frontend/Dockerfile:3-4`
    uses `npm install`, not `npm ci` — builds are not reproducible (backlog B6).
- Prior art: no whole-app project is forkable onto FastAPI (Huly, Plane, Vikunja, Focalboard,
  inbox-zero all drag their own backend; Plane/Vikunja are AGPL). Closest UX match is
  **langchain-ai/agent-inbox** (MIT, 1.1k★, active) — accept/edit/respond/ignore for human-in-the-loop
  agents; its accept path is literally dispatch. **shadcn/ui** (MIT, 124k★) ships the canonical
  three-pane Mail example; `cmdk` palette is MIT but low activity. TanStack Table/Virtual active.
- Streaming: no SSE/WebSocket in the backend today. `fastapi.sse.EventSourceResponse` landed in
  0.135; repo is pinned at 0.115, so live output needs `sse-starlette` (BSD-3, active) or a bump.
  SSE breaks under GZipMiddleware and needs `X-Accel-Buffering: no` through nginx.

## Options
| # | What | Pros | Cons | Effort |
|---|------|------|------|--------|
| A | **Close the Source→WorkItem gap** — promotion (rules now, LLM later) so a sync fills the queue | Makes the whole pipeline visibly work; the GUI already renders the result | Doesn't improve the UI itself; needs a rule/LLM decision | M |
| B | **Reproducible frontend first** — commit lockfile, pin versions, `npm ci` | Prerequisite for touching any UI; removes a silent-breakage class | Invisible to the owner | S |
| C | **Rebuild the UI on shadcn Mail** — three-pane + cmdk + TanStack Virtual in the existing SPA | ≥80% of the triage UI, copy-in source, no new service, keeps cookie/CSRF same-origin | Hand-build grouping/kanban; churns a working UI | M |
| D | **Make dispatch real** — MCP server wrapping the loopback API, or spawn agents | Hand-off stops being a clipboard copy | Spawning collides with `read_only: true`; MCP keeps pull model | M |
| E | **Fix the data/security floor** — encrypt content at rest, persist sessions, index + paginate | The plaintext inbox and the unauth'd status route are real exposure | No visible feature | M |

## Recommendation
**B → A → E**, in that order, before any new UI. The product is ~80% built and the owner does not
know it; the one missing link is Source→WorkItem promotion, which is why the GUI looks dead after a
sync. Rebuilding the UI (C) first would polish a surface that still has nothing to display.

## Open questions
1. Promotion by deterministic rules, or the repo's first LLM call?
2. Is Jira real for v1, or is Outlook+Teams the actual scope?
3. Should dispatch launch an agent (drops `read_only: true`) or stay a queue agents poll?
4. Is plaintext mail content in SQLite acceptable for now?

## Decisions (owner, 2026-09-18)
1. **Promotion: rules now, LLM later.** Deterministic Source→WorkItem promotion first, so the
   pipeline visibly works with no new dependency; LLM cleaning/grouping is a separate later step.
2. **v1 sources: Outlook email, Teams chat, Jira, Freshservice.** Not Slack. Outlook and Teams are
   already implemented via Graph; Jira and **Freshservice** are both net-new connectors with zero
   code and zero config keys in the repo today — each is its own auth story and its own M.
   Sequencing matters: Outlook+Teams need only promotion (A) to become visible, so they should
   prove the pipeline before either new connector is written.
3. **Hand-off: MCP server over the existing loopback API.** No process spawning in the backend,
   `read_only: true` stays, and it matches the pull model `tests/agent_protocol` already pins.
   Claude Code, Codex and opencode can all consume it.
4. **Frontend artefacts: keep `frontend/package-lock.json`** (closes backlog B6, with `npm ci` in
   `frontend/Dockerfile:3-4`); gitignore `*.tsbuildinfo` and the generated `vite.config.js`/`.d.ts`.

## Jira + Freshservice facts (scout 4)
- **Both need new `SourceKind` enum members and a migration** (`backend/app/models.py:25-28`). The
  `"jira:{key}"` / `"freshservice:{id}"` prefix pattern fits `Source.external_id` unchanged
  (`models.py:60`). `sync()` is hardwired to Graph and asserts the connected user id
  (`services/sync.py:35-50`) — it needs per-source dispatch before any connector is added.
- **`httpx` is currently a dev-only dependency** (`backend/pyproject.toml`); the existing Graph
  client is urllib-based, GET-only, with an injectable transport (`integrations/graph.py:18-36`).
- **`EncryptedTokenStore` is single-slot** — one path, AAD `b"workboard-graph-v1"`
  (`services/crypto.py:23-48`). Two more credentials need their own paths and AAD.
- **Jira**: `/rest/api/3/search` is deprecated *and already removed*; the replacement is
  `/rest/api/3/search/jql` with cursor pagination (`nextPageToken`, no `total`). "My work" is
  `assignee = currentUser() ORDER BY updated DESC`, incremental via `AND updated >= "-15m"`.
  Credential is a personal API token + Basic auth, no admin needed. 429 carries `Retry-After`;
  100 rps burst — polling is trivially inside budget.
- **Freshservice**: Basic auth with an API key, but **only agents have API keys** and the role needs
  "Manage API" — a requester account has no key and the connector is dead on arrival. No read-only
  scoping: the key inherits the full agent role. `GET /api/v2/tickets?updated_since=…&per_page=100`
  (offset pagination, default window only 30 days). Rate limit is 100–500/min by plan with a
  List-Tickets sublimit of 40–140.
- **Webhooks are not an option for either** (Jira needs a Connect/Forge app; Freshservice needs the
  admin-only Workflow Automator plus a public URL). Polling is the only realistic local route.
- **No maintained Freshservice SDK exists** (best candidate has 8★). For Jira,
  `atlassian-python-api` (Apache-2.0, 1.7k★, active) and `jira` (BSD-2, 2.1k★) both support
  `search/jql`. Recommendation from the scout: raw `httpx` clients for both, mirroring the Graph
  client's injectable-transport shape — same test seam, no wrapper lag on Jira's churning API.

## Open questions still outstanding
- Is Teams chat actually reachable in the owner's tenant, or will `Chat.Read` need admin consent?
- Plaintext mail/chat content in SQLite (`services/graph.py:50`): acceptable for now, or part of v1?
- Does v1 mean all four sources shipped, or the pipeline proven on Outlook+Teams with Jira and
  Freshservice as follow-on contracts?
- **Is the owner's Freshservice account an agent with "Manage API"?** If it is a requester account
  there is no API key at all and that connector cannot be built.
- Freshservice plan (sets the 100–500 req/min ceiling) and whether the account uses workspaces
  (adds `workspace_id` to every call). Jira: classic API token (site URL) or scoped token
  (needs cloudId and the `api.atlassian.com` base)?
