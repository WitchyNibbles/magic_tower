# Measuring the heuristic on a second PC

The promotion heuristic in `backend/app/services/promotion.py` can only be trusted
once it has been checked against real mail, but real mail must never enter this
repository (`~/.magic-tower/` and any `labeled-sample.json` are gitignored
everywhere in this checkout). In practice that makes it a two-machine problem:
the machine that develops and runs CI never sees real mail, and the machine that
signs in to Outlook is not this repository's remote. This document is the exact,
ordered, pasteable sequence for **the machine with Outlook access** -- call it
the second PC -- from a fresh `git clone` through a printed precision/recall
number. [What actually needs real credentials](#what-actually-needs-real-credentials)
says exactly which of these commands were run on the machine this document was
written on, which one could not be, and why -- so what is proven here stays
separable from what is merely written down.

This file owns the full ordered walkthrough. The README's "Configure the Graph
familiar" and "Measure the heuristic against real mail" sections stay as
reference material -- what the Graph scopes mean, why the two-machine split
exists -- and point here for the runnable sequence, so the steps live in one
place instead of two copies that can drift apart.

## Prerequisites

Before touching a keyboard on the second PC, have on hand:

- A Microsoft Entra application registration for the target work/school account,
  with the exact redirect URI `http://localhost:8787/api/auth/callback` and
  delegated read-only scopes `User.Read`, `Mail.Read`, and `offline_access`.
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
  through the running API container.
- `git`, for the clone in [step 1](#1-clone).
- `python3`, which [step 2](#2-configure-env) uses to generate the two local
  secrets.
- [`uv`](https://docs.astral.sh/uv/). Only [step 7](#7-evaluate) (scoring the
  labeled sample) runs standalone with `uv`, since it reads nothing but the
  JSON file the export step wrote; the README's
  [Develop the API with uv](../README.md#develop-the-api-with-uv) section covers
  installing it and what the backend project expects.

Docker on its own is not enough. `git`, `python3` and `uv` are all pasted before
[step 4](#4-sign-in-and-sync) -- the only step that needs a Microsoft credential
-- so a machine missing any of them stops well before the one failure this
document warns about.

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

**Check that nothing else is listening on `127.0.0.1:8787` first.** The `web`
service publishes that exact address, and it is the only published port in
`docker-compose.yml`, so if anything already holds it `docker compose up -d`
stops with `ports are not available: exposing port TCP 127.0.0.1:8787` and exits
non-zero. That failure is easy to misread: `api` is started and healthy by then,
so `docker compose ps` still shows something alive while nothing answers on
8787. `ss -ltnp | grep 8787` names whatever holds it. This is not hypothetical
-- it is the one documented command that could not be completed on the machine
this document was written on ([see below](#what-actually-needs-real-credentials)).

## 4. Sign in and sync

Sign in through the GUI's Microsoft sign-in control, which calls
`GET /api/auth/microsoft/start` -- **this is the first line in this document
that needs real Microsoft credentials to succeed** (see below). Once signed in,
trigger a sync from the GUI, which calls `POST /api/sync`; it never sends mail
or acts in Microsoft 365, only reads bounded Outlook metadata.

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

**Step 4 is the one line in this document that a real Entra app registration and
a real Outlook sign-in are required for.** Nothing else in the sequence needs a
Microsoft account: everything below was exercised with blank `MICROSOFT_*`
values and a generated `APP_ENCRYPTION_KEY` and `LOCAL_API_TOKEN`, and the API
answers every request cleanly rather than crashing.

What "was exercised" covers is worth splitting in three, because one documented
command was not among them.

**Run exactly as written, on a machine with no Outlook access:**

- Step 2's two `python3 -c` lines, and `docker compose build` in step 3: exit 0.
  (Step 1 is a plain `git clone` and was not re-run -- this was written from a
  checkout that already existed.)
- Step 5 in full. The export writes `[]` and exits 0 against a database no sync
  has filled -- exactly a real second PC that has not synced yet -- and the
  `mkdir`, `chmod`, `docker compose cp` and `rm` lines leave `~/.magic-tower`
  at `drwx------` with the file inside it.
- Step 7, both ways. Against that empty export, `MAGIC_TOWER_REQUIRE_SAMPLE=1`
  exits non-zero with `... has 0 row(s) and none are labeled`, while the same
  command without the flag exits 0 with "nothing to evaluate" -- the difference
  the flag exists for. Against the committed synthetic
  `backend/app/tools/labeled-sample.example.json`, the strict run prints the
  confusion matrix, precision and recall and exits 0.

**Not completed as written -- `docker compose up -d` in step 3:**

- On the machine this document was written on, an unrelated long-running process
  already held `127.0.0.1:8787`, the address the `web` service publishes. The
  documented command failed with `ports are not available: exposing port TCP
  127.0.0.1:8787` and exited 1; `api` started and went healthy, no `web`
  container was ever created. That port could not be freed on that machine, so
  this line, and the "open http://localhost:8787" that follows it, are **not**
  proven here.
- What was proven instead: the same stack, brought up through a `docker compose
  -f docker-compose.yml -f <override>` file that republishes `web` on a free
  port, starts both services with `api` healthy and serves the GUI. Only the
  published port number differed from the documented command. A second PC where
  8787 is actually free should therefore find step 3 works as written -- but
  that last sentence is inference, not observation, which is why
  [step 3](#3-raise-the-tower) tells you to check the port first.
- Through that overridden stack, on the GUI port:
  - `GET /api/auth/microsoft/start` with no local session or bearer token:
    `401 {"detail":"A local browser session or bearer token is required"}`.
  - The same request with a bearer token but blank `MICROSOFT_*` values:
    `503 {"detail":"Graph configuration is incomplete: MICROSOFT_TENANT_ID, MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, MICROSOFT_TARGET_USER_ID"}`.

**Not run at all -- step 4:** the Microsoft sign-in itself, and the sync it
enables. Those need the real Entra registration and Outlook account that the
machine this was written on does not have.
