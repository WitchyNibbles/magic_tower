# Measuring the heuristic on a second PC

The promotion heuristic in `backend/app/services/promotion.py` can only be trusted
once it has been checked against real mail, but real mail must never enter this
repository (`~/.magic-tower/` and any `labeled-sample.json` are gitignored
everywhere in this checkout). In practice that makes it a two-machine problem:
the machine that develops and runs CI never sees real mail, and the machine that
signs in to Outlook is not this repository's remote. This document is the exact,
ordered, pasteable sequence for **the machine with Outlook access** -- call it
the second PC -- from a fresh `git clone` through a printed precision/recall
number. Every command below was run, on this machine, up to the exact line
named in [What actually needs real credentials](#what-actually-needs-real-credentials);
everything before that line is proven, not merely written down.

This file owns the full ordered walkthrough. The README's "Configure the Graph
familiar" and "Measure the heuristic against real mail" sections stay as
reference material -- what the Graph scopes mean, why the two-machine split
exists -- and point here for the runnable sequence, so the steps live in one
place instead of two copies that can drift apart.

## Prerequisites

Before touching a keyboard on the second PC, have on hand:

- A Microsoft Entra application registration for the target work/school account,
  with the exact redirect URI `http://localhost:8787/api/auth/callback` and
  delegated read-only scopes `User.Read`, `Mail.Read`, `Chat.Read`, and
  `offline_access`.
- **The `Chat.Read` admin-consent risk.** Some tenants require an administrator
  to grant consent for delegated Teams scopes, and the owner of this mailbox may
  not hold or be able to obtain that consent. This is a risk to plan around, not
  a settled requirement: if consent is refused or unavailable, drop `Chat.Read`
  from the app registration and skip Teams ingestion entirely -- mail-only sync,
  export, and heuristic evaluation all still work with `Mail.Read` alone.
- Five `MICROSOFT_*` settings the app registration above produces:
  `MICROSOFT_TENANT_ID`, `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`,
  `MICROSOFT_TARGET_USER_ID` (the signed-in account's Entra object ID), and
  `MICROSOFT_REDIRECT_URI` (the same redirect URI as above).
- `APP_ENCRYPTION_KEY`, a 32-byte URL-safe base64 key this instance generates
  for itself -- see [step 2](#2-configure-env) for the exact command. It
  encrypts the local Graph token store and stored message excerpts; without it
  the API refuses to store or serve them.
- `LOCAL_API_TOKEN`, a separately generated local credential (any random
  string) that gates every write to this instance, including the sync and
  export steps below. It is a Magic Tower-only credential, never a Microsoft
  secret.
- Docker and Docker Compose. Sign-in, sync, and the export step below all go
  through the running API container; only [step 7](#7-evaluate) (scoring the
  labeled sample) runs standalone with `uv`, since it reads nothing but the
  JSON file the export step wrote.

## 1. Clone

```sh
git clone <this repository's URL> magic-tower
cd magic-tower
```

## 2. Configure `.env`

```sh
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"      # -> LOCAL_API_TOKEN
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"  # -> APP_ENCRYPTION_KEY
```

Edit `.env` and fill in the two generated values plus the five Graph settings
from the prerequisites:

```
MICROSOFT_TENANT_ID=...
MICROSOFT_CLIENT_ID=...
MICROSOFT_CLIENT_SECRET=...
MICROSOFT_TARGET_USER_ID=...
MICROSOFT_REDIRECT_URI=http://localhost:8787/api/auth/callback
APP_ENCRYPTION_KEY=<the base64 key generated above>
LOCAL_API_TOKEN=<the token generated above>
```

Leave `PROMOTION_ALLOWLISTED_SENDERS` for later if there is a robot sender whose
mail should always count as work regardless of the heuristic's rules.

## 3. Raise the tower

```sh
docker compose build
docker compose up -d
```

`docker compose ps` should show `api` healthy. Open
[http://localhost:8787](http://localhost:8787) and enter the `LOCAL_API_TOKEN`
from `.env` to start a local session.

## 4. Sign in and sync

Sign in through the GUI's Microsoft sign-in control, which calls
`GET /api/auth/microsoft/start` -- **this is the first line in this document
that needs real Microsoft credentials to succeed** (see below). Once signed in,
trigger a sync from the GUI, which calls `POST /api/sync`; it never sends mail
or acts in Microsoft 365, only reads bounded Outlook/Teams metadata.

## 5. Export the synced sources for hand-labeling

```sh
docker compose exec api python -m app.tools.heuristic_export --output /data/labeled-sample.json
mkdir -p -m 700 ~/.magic-tower
chmod 700 ~/.magic-tower
docker compose cp api:/data/labeled-sample.json ~/.magic-tower/labeled-sample.json
docker compose exec api rm /data/labeled-sample.json
```

`docker compose cp` cannot read the container's `/tmp` tmpfs, so the export
writes into the `workboard-data` volume at `/data` and the copy pulls it out
from there. The file itself is written `0600` (an explicit `chmod` no umask can
loosen); the `mkdir -p -m 700` and `chmod 700` above are what keep the
*directory* owner-only, since `mkdir` only applies a mode when it actually
creates the directory, and on a fresh second PC nothing has created
`~/.magic-tower` yet.

## 6. Label the sample by hand

Open `~/.magic-tower/labeled-sample.json`. Each row carries the fields
`should_promote` reads (sender, recipients, headers, an excerpt) plus an empty
`label` field. Set `label` to `true` on rows that belong in the triage queue,
`false` on rows that do not, and leave the rest `null`. See
`backend/app/tools/labeled-sample.example.json` for the (entirely synthetic)
row shape. This file holds real mail; it never needs to leave this machine.

## 7. Evaluate

```sh
cd backend
MAGIC_TOWER_REQUIRE_SAMPLE=1 uv run python -m app.tools.heuristic_eval \
    --sample ~/.magic-tower/labeled-sample.json \
    --owner-address you@tenant.com --owner-address you@tenant.onmicrosoft.com
```

This prints the confusion-matrix counts plus precision and recall. Name every
address the owner receives mail at with `--owner-address` -- both the
`userPrincipalName` and the mail address, since alias-domain tenants hand out
different ones -- or the "skip mail you were only copied on" rule (rule 4)
never fires and the reported precision comes out lower than the heuristic
actually achieves.

`MAGIC_TOWER_REQUIRE_SAMPLE=1` is what makes this the second PC's own proof,
not a step that can be skipped and still look done: with it set, a sample that
is missing, or one that was exported but never labeled, is a hard failure
(non-zero exit, a message on stderr naming the sample path) instead of the
default's quiet "nothing to evaluate" -- see the module docstring of
`backend/app/tools/heuristic_eval.py` for the exact rules. Without it (the
default everywhere else, including CI), an absent or unlabeled sample exits 0,
which is what lets the test suite and a machine that has never synced real mail
stay green.

## What actually needs real credentials

Steps 1 through 3 above, and the export/label/eval mechanics in steps 5
through 7, run with no Microsoft account at all -- they were run exactly as
written, on this machine, against a `docker compose` stack with a generated
`APP_ENCRYPTION_KEY` and `LOCAL_API_TOKEN` and blank `MICROSOFT_*` values, and
the API answers every request cleanly rather than crashing:

- `GET /api/auth/microsoft/start` with no local session or bearer token:
  `401 {"detail":"A local browser session or bearer token is required"}`.
- The same request with a bearer token but blank `MICROSOFT_*` values:
  `503 {"detail":"Graph configuration is incomplete: MICROSOFT_TENANT_ID, MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, MICROSOFT_TARGET_USER_ID"}`.
- `heuristic_export` against a database with no synced sources exits 0 and
  writes an empty array, exactly as it would on a real second PC that has not
  synced yet.
- `heuristic_eval`, both with and without `MAGIC_TOWER_REQUIRE_SAMPLE=1`,
  behaves exactly as documented in step 7 against that empty export and
  against the committed synthetic example.

**Step 4 is the one line in this document that a real Entra app registration
and a real Outlook sign-in are required for.** Everything before it, and every
mechanical step after it, is proven on a machine with no Outlook or Teams
access at all.
