# Magic Tower

![Magic Tower, surrounded by floating runic particles](assets/magic-tower-logo.png)

*A quiet, local-first tower for tending the work that finds you.*

Magic Tower is a local-first workboard for tasks found in a specific Outlook mailbox and Teams conversations. Microsoft Graph ingestion and agent-driven work extraction are deliberately opt-in: nothing crosses the threshold until you invite it in.

## Raise the tower locally

```sh
cp .env.example .env
docker compose up --build
```

Open [http://localhost:8787](http://localhost:8787). The web service binds to loopback only; the API stays inside the Compose network. Stop with `docker compose down`; persistent SQLite data is held in the `workboard-data` Docker volume.

On first use, enter the separately generated `LOCAL_API_TOKEN` in the browser to create an HttpOnly, eight-hour local session. The typed value is not persisted in browser storage; cookie-backed changes also require CSRF protection.

## What waits within

- A clean local dashboard can filter, inspect, update, and dispatch pending work with source evidence.
- SQLite-backed work items, sources, evidence, agent proposals, and auditable dispatch records.
- Delegated Microsoft OAuth with PKCE, `/me`-only Outlook and Teams-chat ingestion, bounded excerpts, and encrypted local token storage.
- An installable Codex plugin/skill plus a Claude Code command and loopback-only JSON CLI in `scripts/pending-work`.

## Configure the Graph familiar

Register a Microsoft Entra application for the intended work/school account. Add the exact redirect URI `http://localhost:8787/api/auth/callback`, configure delegated read-only scopes `User.Read`, `Mail.Read`, `Chat.Read`, and `offline_access`, then set the tenant, client, target object ID, and separately generated `APP_ENCRYPTION_KEY` in `.env`. Some tenants require administrator consent for Teams scopes. The connector uses `/me` only and rejects a sign-in whose object ID does not match `MICROSOFT_TARGET_USER_ID`.

Use `GET /api/auth/microsoft/start` to begin sign-in, then `POST /api/sync` to import bounded Outlook/Teams metadata. It never sends messages or acts in Microsoft 365.

## Agent integration

Set a separate random `LOCAL_API_TOKEN` in `.env`, then expose it to the agent process as `PENDING_WORK_API_TOKEN`. It is a Magic Tower-only credential, never an Azure or Graph token. See [the agent protocol](docs/agent-protocol.md) for installation and exact commands.

## The warding circle

The API is loopback-only through Compose, Graph tokens are AES-GCM encrypted at rest, and agent operations require the local token. This is a trusted-local-host design, not protection from a compromised browser profile, Docker host, or local administrator. Keep `.env` local, never store raw Graph credentials in the database, and retain only source excerpts necessary to explain a work suggestion.

## License

Magic Tower is released under the [MIT License](LICENSE).
