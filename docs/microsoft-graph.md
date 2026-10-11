# Microsoft Graph

How to connect Outlook, what the first sync and the backfill do, and how the promotion heuristic is measured. The scopes and security model are summarized in the README's [Security](../README.md#security) section.

## Register the application and connect

Register a Microsoft Entra application for the intended work/school account. Add the exact redirect URI `http://localhost:8787/api/auth/callback` (matching `MICROSOFT_REDIRECT_URI`, so use your own port if you changed `WEB_PORT`), configure delegated read-only scopes `User.Read`, `Mail.Read`, and `offline_access`, then set the tenant, client, target object ID, and separately generated `APP_ENCRYPTION_KEY` in `.env`. The connector uses `/me` only and rejects a sign-in whose object ID does not match `MICROSOFT_TARGET_USER_ID`.

Use `GET /api/auth/microsoft/start` to begin sign-in, then `POST /api/sync` to import bounded Outlook metadata. It never sends messages or acts in Microsoft 365.

If the database holds `sources` rows written before the promotion heuristic existed, call `POST /api/sync/backfill` once to offer them to it; it never runs on its own (not at startup, not from `POST /api/sync`), reaches no network, and is safe to call again -- a source it has already judged, promoted or not, is never re-judged. Its response reports `considered`, `new_work_items`, `judged_without_context` and `promoted_without_owner_check` separately, because a bare `new_work_items` count cannot tell "nothing left to backfill" apart from "backfilled some and the heuristic declined all of it".

The backfill judges slightly less well than a live sync does, and the last two counts are how it says so. `judged_without_context` counts rows stored before the sender and headers were kept at all, which can only be promoted unconditionally. `promoted_without_owner_check` counts rows promoted without the "skip mail you were only copied on" rule: that rule needs your own addresses, only the live Graph profile has them, and nothing stores them -- so **mail you were merely Cc'd on is promoted by the backfill even though a sync would decline it**. Both counts are rows worth reviewing in the queue, not errors; dismiss what does not belong.

## Measure the heuristic against real mail

The promotion heuristic in `app/services/promotion.py` can only be trusted once it has been checked against real mail, but real mail must never enter this repository. This is a two-machine workflow: sign in and sync on the machine with Outlook access, then hand-label and evaluate.

`heuristic_export` reads the database a sync wrote to and never talks to Microsoft Graph. `heuristic_eval` reads only the labeled-sample JSON file it produces -- no database, no Graph credentials -- so it also runs safely on a machine that has never synced real mail: with no sample file present it prints a message and exits 0, and `MAGIC_TOWER_REQUIRE_SAMPLE=1` turns that (and an exported-but-never-labeled sample) into a hard failure instead, for the one run that is meant to prove the heuristic was actually checked. See `app/tools/labeled-sample.example.json` for the (entirely synthetic) row shape.

See [`docs/second-pc.md`](second-pc.md) for the full, ordered, pasteable sequence -- from `git clone` to a printed precision/recall number -- including every prerequisite (the five `MICROSOFT_*` settings, `APP_ENCRYPTION_KEY`, and `LOCAL_API_TOKEN`) and exactly how far it runs without real Microsoft credentials.
