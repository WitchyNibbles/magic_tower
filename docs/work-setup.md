# Setting up on a work computer

How to run Magic Tower on a Windows work PC with WSL2 and Docker Engine inside WSL, so you can develop it and test it against your real Jira. Outlook works only if IT registers an app for you (step 5). Each step ends with a check, so you know it worked before you move on.

Read this first: today a Jira sync only fetches issues updated in the last 15 minutes, and nothing syncs on a schedule (`docs/status.md`, gap 1). The steps below get everything running and prove the connection. Daily use needs that fixed first.

`docs/jira-setup.md` and `docs/second-pc.md` have the long versions of the Jira and Outlook steps. This page puts them in order.

Placeholders like `<site>` and `<you@company>` stand for your own values. Real values go in `.env` and `~/.magic-tower/` only. This repo is public: no company names, hosts, addresses, tickets or mail go into a commit, an issue or a PR.

## 0. What you need

| Thing | Why | Check |
| --- | --- | --- |
| WSL2 with Ubuntu (or similar), systemd on | everything runs here | `wsl -l -v` in PowerShell shows version 2; `systemctl is-system-running` answers in WSL |
| `git`, `curl`, `jq` | clone, installs, the dead-code tests | `git --version && jq --version` |
| `uv` | backend (it fetches Python 3.12 by itself) | `uv --version` |
| Node 22 + npm | frontend dev and tests | `node --version` → `v22.*` |
| Docker Engine + Compose 2.24 or newer, inside WSL | the real app stack | `docker compose version` |
| A Jira Cloud site (`<site>.atlassian.net`) | Jira sync | the Jira URL ends in `atlassian.net` |
| `gh` (optional) | PRs from the terminal | `gh auth status` |

If systemd isn't on, put `[boot]` + `systemd=true` in `/etc/wsl.conf`, run `wsl --shutdown` in PowerShell, and reopen WSL. Docker Engine runs as a systemd service.

### Behind a company proxy

Skip this if `curl -sI https://<site>.atlassian.net` and `curl -sI https://download.docker.com` both answer from WSL. Otherwise do it before installing anything.

Add the proxy to your shell profile (`~/.bashrc` or your shell's equivalent), then open a new shell:

```sh
export HTTPS_PROXY=http://<proxy-host>:<port>
export HTTP_PROXY=http://<proxy-host>:<port>
export NO_PROXY=localhost,127.0.0.1,api
# apt reads only the lowercase names
export https_proxy=$HTTPS_PROXY http_proxy=$HTTP_PROXY no_proxy=$NO_PROXY
```

`apt`, `curl`, `git`, `uv` and `npm` read these. Docker needs it in two places once it's installed: a systemd drop-in for `docker.service` for image pulls (Docker's docs: "Configure the daemon to use a proxy"), and `proxies` in `~/.docker/config.json` for the `RUN npm ci` and `RUN uv sync` steps of the image builds. Step 3 adds it to `.env` for the running app.

If the company also inspects TLS with its own root CA:

1. Add the CA to WSL: copy it to `/usr/local/share/ca-certificates/<name>.crt`, then `sudo update-ca-certificates`.
2. Make uv and Node trust it. Add to your shell profile:

```sh
export UV_SYSTEM_CERTS=1
export NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/<name>.crt
```

3. The Docker image builds can't use it yet: the Dockerfiles have no CA hook, so `docker compose build` fails at `npm ci` or `uv sync`. Until that's added, develop with the no-Docker loop in step 9, which runs fine.

## 1. Install the tools

Ubuntu in WSL:

```sh
sudo apt-get update && sudo apt-get install -y git curl jq
curl -LsSf https://astral.sh/uv/install.sh | sh
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
```

On WSL the Docker script prints a warning suggesting Docker Desktop and waits 20 seconds. Let it carry on. Then close the WSL window and open a new one (that loads uv, nvm and the `docker` group), and run:

```sh
nvm install 22
```

Behind a proxy, set up the Docker daemon proxy (section above) before this check, since it pulls from Docker Hub. Check: `docker run --rm hello-world` prints "Hello from Docker!", and the table checks above pass.

## 2. Clone and run the tests

Use a path under `~`, not under `/mnt/c`: tests and Docker are much slower on the Windows drive.

```sh
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/WitchyNibbles/magic_tower.git magic-tower
cd magic-tower
git config user.name "<your public name>"
git config user.email "<your public commit email>"
cd frontend && npm ci && npm run test -- --run && cd ..
cd backend && uv sync && uv run pytest && cd ..
```

Use your personal identity, not the work one: commits go to a public repo.

Run `npm ci` before pytest: the dead-code tests in the backend suite need `frontend/node_modules`, and they also fetch `knip` and `vulture` from the network. Run pytest from `backend/`, where the uv project lives.

Check: both suites end green. If `docker compose config` doesn't work in WSL yet, the 3 `test_docker_compose.py::test_web_port_*` tests fail. They pass once Docker works.

## 3. Make `.env`

From the repo root:

```sh
cp .env.example .env
chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"                                 # LOCAL_API_TOKEN
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"      # APP_ENCRYPTION_KEY
```

Paste the two values into `.env`. Behind a proxy, add the same three proxy settings there too, without `export`: Compose passes `.env` into the `api` container, and the app's Jira and Graph calls (stdlib `urllib`) use them. Leave the `MICROSOFT_*` lines blank unless step 5 happens.

`.env` is gitignored. Never paste its values into a chat, issue or commit.

## 4. Connect Jira

1. Create a classic API token at <https://id.atlassian.com/manage-profile/security/api-tokens> (not a scoped one).
2. Fill in `.env`: `JIRA_SITE_URL=https://<site>.atlassian.net`, `JIRA_ACCOUNT_EMAIL=<you@company>`, `JIRA_API_TOKEN=<token>`.
3. Optional: `JIRA_MANAGEMENT_PROJECT_KEY=<KEY>` for one project you want to browse but not get tasks from. That fetch has no 15-minute window: it reads up to 2000 of the project's issues, newest first.
4. Check without starting the app:

```sh
cd backend
uv run --env-file ../.env python -m app.tools.jira_check
cd ..
```

Check: it prints `connected to https://<site>.atlassian.net as '<your name>' ...` and an issue count. The count covers only issues you touch that changed in the last 15 minutes, so `0` is normal. `Jira request failed with status 401` means a wrong email or token. Plain `Jira request failed` means DNS, TLS or proxy (see the proxy section).

## 5. Outlook: only through IT

You can't register an Entra app at work, and Magic Tower has no other way in: it reads mail only through Microsoft Graph with its own app registration. Skip this step unless IT agrees. Everything else works without it.

If you want Outlook, first check that a local, encrypted copy of your work mail excerpts is OK under company policy. Then ask IT for one of these:

- They register the app for you and send you the tenant ID, client ID and a client secret.
- Or they give you the Application Developer role, so you can register it yourself.

What the app needs, to paste to IT:

```text
App registration, single tenant, for a local tool that reads only my own mailbox.
Platform: Web. Redirect URI: http://localhost:8787/api/auth/callback
Microsoft Graph delegated permissions: User.Read, Mail.Read, offline_access (nothing else)
A client secret (the app is a confidential client using auth code + PKCE)
If user consent is off: admin consent for those three permissions
```

Once you have them, fill in `.env`: `MICROSOFT_TENANT_ID`, `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_TARGET_USER_ID` (your own Entra object ID: Entra → Users → you → Object ID), and `MICROSOFT_REDIRECT_URI=http://localhost:8787/api/auth/callback`. If you change `WEB_PORT`, the redirect URI has to change in both places.

If IT only allows public-client apps (no secret), Magic Tower needs a small code change first: today it refuses to start Graph sign-in without `MICROSOFT_CLIENT_SECRET`.

## 6. Start the app

```sh
ss -ltnp | grep 8787 || echo "8787 is free"
docker compose up -d --build --wait
docker compose ps
```

Check: `api` shows healthy and `web` shows running. Open <http://localhost:8787> in your Windows browser and type the `LOCAL_API_TOKEN`.

If Windows can't reach the page but `curl -s http://127.0.0.1:8787/api/health` works inside WSL, WSL isn't forwarding localhost. Put `[wsl2]` + `networkingMode=mirrored` in `%UserProfile%\.wslconfig`, run `wsl --shutdown`, and start again.

## 7. First real sync

The UI's sync button syncs Outlook only, so with no Outlook it just says "Sync could not be completed." Sync Jira from the repo root. The parentheses keep the `.env` secrets out of your shell afterwards:

```sh
( set -a; . ./.env; set +a
  curl -s -w '\n%{http_code}\n' -X POST "http://localhost:8787/api/sync?kind=jira" \
    -H "Authorization: Bearer $LOCAL_API_TOKEN" )
```

Check: `200` and a JSON body with `count`. To see something come back, update an issue assigned to you (a comment is enough), then sync within 15 minutes. Reload the UI and filter by source "Jira". Only issues assigned to you become work items. The rest are stored and browsable.

On a `500`, run `docker compose logs api --tail 50`. The real reason is there.

With Outlook set up: press connect in the UI and sign in. The sign-in replaces the page, and you end on a "Microsoft Graph connected" page. Go back to <http://localhost:8787> (your session survives) and press sync. Items show up under source "Outlook". Each sync reads the newest 50 messages in the Inbox folder only.

## 8. Daily use (once gap 1 is fixed)

There's no scheduler yet, and the Jira window is 15 minutes, so a manual sync once a day misses almost everything. For now, a day of real testing looks like this:

1. `docker compose up -d` (the data lives in the `workboard-data` volume between runs).
2. Run the Jira `curl` above every few minutes while you work, or right after touching an issue.
3. Triage the queue: update, dismiss, hand off. Note what's missing or noisy. Those notes are the backlog.
4. `docker compose down` when done. `down -v` deletes all synced data.

Freshservice tickets don't show up: there's no Freshservice connector yet (`docs/status.md`, gap 5).

With Outlook, after a week or so, score the promotion rules on your own mail with `docs/second-pc.md` steps 5 to 7. The labeled file holds real mail and stays in `~/.magic-tower/`, outside the repo.

## 9. Develop there

Fast loop without Docker. The backend reads the root `.env` for the tokens and keys, and the shell values below override its Docker-only paths:

```sh
mkdir -p -m 700 ~/.magic-tower
cd backend
export DATABASE_URL=sqlite:///./workboard.db TOKEN_STORE_PATH=$HOME/.magic-tower/graph-tokens.json OAUTH_STATE_STORE_PATH=$HOME/.magic-tower/oauth-state.json
uv run --env-file ../.env alembic upgrade head
uv run --env-file ../.env uvicorn app.main:app --reload
```

In a second shell: `cd frontend && npm run dev`, then open <http://localhost:5173> (Vite proxies `/api` to `:8000`). Jira works here too. Microsoft sign-in only works through the `:8787` stack unless the app gets a second redirect URI for `:5173`.

- Real data stays on the work PC. Bugs found with real tickets go into tests as made-up fixtures, never copied ticket or mail text.
- Branch, push and open a PR as usual. CI runs the backend suite, the frontend suite and the compose build.
