# Agent protocol

Agent integrations are installable commands or skills that communicate with Workboard's local API; they are not embedded with unrestricted credentials.

## Intake contract

1. The connector supplies a normalized email with a stable external ID and deep link.
2. The agent identifies actionable, pending work and returns a proposed `WorkItemCreate` payload.
3. Each proposal includes source evidence (`source_kind`, external ID, optional minimal excerpt, observed time).
4. The API validates the schema, records provenance, and returns a reviewable item. The user confirms or edits it in the UI.

## Dispatch contract

When the user selects “Address with Codex” or “Address with Claude Code”, Workboard will create an `AgentDispatchRequest` containing a work-item ID, an explicit client identifier, and a user-authored/bounded instruction. The installed integration resolves the item from localhost, shows the planned work in its native UI/TUI, and requires the agent client's normal approval flow for side effects.

Integrations must:

- use localhost API access only and never transmit stored mailbox content to a third party without user approval;
- preserve the work-item ID in progress/result updates;
- treat source excerpts as sensitive and minimize them in prompts/logs;
- report uncertainty rather than silently marking work complete.

## Clients

This repository ships the API side of the protocol only. A client talks to `http://127.0.0.1:8787/api` and authenticates with Workboard's distinct `LOCAL_API_TOKEN`.

The token is sent only as a Bearer header to loopback. It is never a Graph token. `health` and `status` are uncredentialed; agent context, proposals, updates, and dispatches require the token.
