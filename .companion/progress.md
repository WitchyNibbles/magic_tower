2026-09-17 — contract sealed (2ca56e84), 6 tasks todo, next: T01 commit the uv migration

## 2026-09-17T19:15:24Z · T01 · verified
- attempt: 2 · model: opus · reviewer: fable (opus authored the repair, so the reviewer must differ)
- commits: 418eba1
- commands: done-when → exit 0; test → exit 0 (18 passed, main tree); probe: RED
- review: approve
- notes: attempt 1 (sonnet, ed8f246) rejected by manager — the harness creates agent worktrees from `main` (05bc7f3), not from HEAD, so its branch was not fast-forwardable and its diff deleted all of `.companion/`. Repair worker reset onto base first. Adding `[build-system]` (setuptools, per egg-info `top_level.txt = app`) made the project non-virtual, so `uv.lock` had to be regenerated — the committed lock supersedes the copy that was untracked in the primary tree; T02 must take pyproject/lock from git, not re-copy. Suite is green in the main tree only because untracked `conftest.py` is still there; a fresh clone is still red (13 passed, 5 errors, `Engine(sqlite:////data/workboard.db)` at import) — that is T02's to close. `.claude/` worktree dir is untracked and not gitignored; out of T01 scope but it will dirty AC10.

## 2026-09-17T19:27:35Z · T02 · verified
- attempt: 1 · model: sonnet · reviewer: opus
- commits: a0d7019
- commands: done-when → exit 0 (18 passed, fresh clone of main tree); test → exit 0 (18 passed, main tree); probe: VACUOUS — false positive, see notes
- review: approve (2 advisories, both non-blocking: stray leading blank line at conftest.py:1; README "After changing"→"When dependencies move" is avoidable wording churn)
- notes: probe reverted only README.md — its TEST_PATH regex classifies conftest.py/test_*.py as test paths, so T02 (test files + docs, no impl file) has nothing revertible; reverting a README cannot redden a suite. Real RED confirmed by manager at base: fresh clone → exit 1, 13 passed / 5 errors, `unable to open database file '/data/workboard.db'`. Reviewer re-probed properly by stubbing the fixture body to a bare `yield` → 2 failures, so the fixture is load-bearing. Merge needed care: the owner's uncommitted copies of all four files sat in the primary tree; diffed each against the branch first — only differences were T02's intended corrections, so nothing was lost. The guard forbids deleting test files, so the untracked conftest.py was staged (blob identical to a0d7019's) to let the ff-only merge through rather than removed. README line 61 `changes`→`writes` is forced by AC3's case-insensitive substring grep matching "changes"; reviewer confirms it does not weaken the claim (test_security.py:30-33 asserts cookie GET 200 / cookie POST without CSRF 403). T03 still has its full charter: conftest.py:8 still pins `sqlite:////tmp/workboard-tests.db` at import time — T03 should drop the stray blank line at conftest.py:1 while it is in there. `.claude/` remains untracked and un-ignored; still an AC10 hazard for a later task.

## 2026-09-17T19:49:10Z · T03 · verified
- attempt: 2 · model: opus · reviewer: fable (opus authored the repair, so the reviewer must differ)
- commits: 3e36fdd
- commands: done-when → exit 0 (parallel 3 rounds, real per-job exits 0/0, 9 passed each); test → exit 0 (19 passed, was 18); probe: RED but uninformative (0 files reverted)
- review: approve (no findings; attempt 1 was revised for "no test was added — the regression guard lived only in the done-when command")
- notes: attempt 1 (sonnet, 1ec921a) changed only conftest.py — correct fix, but nothing in the repo would catch a regression, so opus reviewed it `revise`; repair added `backend/tests/test_database_isolation.py`, which spawns two bare interpreters that import conftest and asserts their DATABASE_URLs differ. Manager falsified it twice: base conftest → FAIL, and a fixed-constant dir that still satisfies the done-when grep → FAIL, so the test is not a restatement of the grep. Plan text says `tmp_path_factory`; the code uses `tempfile.mkdtemp` at conftest import time — the deviation is required (a fixture resolves after conftest has already imported `app.database`) and both reviewers endorsed it; plan.md wording left as-is. `atexit.register(shutil.rmtree, ..., ignore_errors=True)` stops the per-process temp dir leaking; it cannot race the import-time engine. Two facts for later tasks: (1) the done-when's bare `wait` returns 0 regardless of job status, so that command cannot actually fail on a test failure — the manager checked per-job exits with `wait $PID` instead; T06's CI should not rely on `... & ... & wait` as a gate. (2) suite count is now **19**, and `.claude/` is still untracked and un-ignored — an AC10 hazard nobody has claimed yet.

## 2026-09-17T20:07:00Z · T04 · verified
- attempt: 2 · model: opus · reviewer: fable (opus authored the repair, so the reviewer must differ)
- commits: 79bf111
- commands: done-when → exit 0 (21 passed, main tree); test → exit 0 (21 passed, was 19); probe: RED
- review: approve (2 advisories, both non-blocking — see notes)
- notes: attempt 1 (sonnet, 93f94c7) probed VACUOUS and was rejected: same pyproject change, but its guard spawned an inner pytest with explicit `--timeout=1 --timeout-method=thread`, proving only that the plugin was installed. Manager falsified it by deleting both ini keys — guard stayed green (exit 0, 1 passed). The repair's guard interrogates the running session instead: `pytestconfig.pluginmanager.hasplugin("timeout")` + `getini("timeout")`/`getini("timeout_method")`, plus a behavioural check that a `threading.Timer` named `pytest_timeout <nodeid>` is live for the current item — so the thread method being in force is proved without paying the 30s wait (the signal fallback starts no thread). Manager re-falsified all three ways independently, full suite each time: `timeout` deleted → exit 1; `timeout_method` deleted → exit 1; `pytest-timeout` uninstalled → exit 1. Real behaviour confirmed with **no CLI flag**: a planted `time.sleep(300)` test → exit 1 after 33s with a dumped stack and `+++ Timeout +++`. Three facts for later tasks: (1) suite count is now **21**; (2) the guard couples to pytest-timeout's internal timer-thread naming (`pytest_timeout.py:324`) — safe while `==2.3.1` is pinned in `uv.lock`, but a version bump needs a one-line update, and running with `--timeout-method=signal` fails it by design; (3) reviewer advisory worth acting on somewhere: `backend/tests/test_database_isolation.py:16` uses `subprocess.run(..., timeout=60)`, which now sits *above* the 30s watchdog — if that child hangs, the session-level watchdog `os._exit(1)`s first, so the failure is misattributed and `conftest.py:15`'s `atexit` rmtree is skipped (temp DB dir leaks); lowering it below 30s makes the narrower guard fire first. `.claude/` is still untracked and un-ignored — an AC10 hazard nobody has claimed yet.

## 2026-09-17T20:31:00Z · T05 · verified
- attempt: 1 · model: sonnet · reviewer: opus
- commits: 23d6c70
- commands: done-when → exit 0 (2 passed, 11 deselected, main tree); test → exit 0 (23 passed, was 21); probe: RED but uninformative (0 files reverted — test-only diff)
- review: approve (2 advisories, both non-blocking, both about partial selection — see notes)
- notes: fix is two test-only files, `app/security.py` untouched; `_clear_session_store()` in conftest takes `_sessions_lock` and calls `dict.clear()` in place (rebinding would desynchronise importers) in both fixture setup and teardown — reviewer showed each clear is individually sufficient, so one is redundant, but it mirrors the existing `cache_clear`/`drop_all` symmetry and was left. Manager falsified by hand, twice: conftest reverted to base + test kept → done-when exit 1 with the leaked dict in the assertion message, and full suite → 1 failed / 22 passed. AC5 re-checked → exit 0; AC10 dirt is only `.companion/plan.md` and the pre-existing `.claude/`, nothing new from this diff; `../tests/agent_protocol` standalone still 10 passed (backend conftest is not loaded for that path). **Three facts for T06:** (1) suite count is now **23**; (2) the guard is a *pair* of order-dependent tests in `backend/tests/test_session_isolation.py` — the first seeds a session, the second asserts `_sessions == {}`. Reviewer verified that running the assertion test alone, or any `-k` narrower than the done-when, passes even with the fix fully reverted, so CI must run the whole file in one in-order, single-process session; (3) consequently T06 must **not** add `pytest-xdist -n auto` or `pytest-randomly` — neither is installed today (checked `pyproject.toml` dev group and `uv.lock`), and either would silently neuter this guard. A sentinel set by the seed test and asserted by the second would harden it; not done here, out of T05 scope.

## 2026-09-17T20:36:02Z · T06 · verified
- attempt: 1 · model: sonnet · reviewer: opus
- commits: 56a6824
- commands: done-when → exit 0; test → exit 0 (26 passed, was 23); probe: RED (3 impl files reverted — ci.yml, pyproject.toml, uv.lock)
- review: approve (3 advisories, all non-blocking — see notes)
- notes: workflow triggers push+pull_request; test job = checkout@v4 + setup-uv@v5 (python-version 3.12) + `uv sync` + `uv run pytest tests ../tests/agent_protocol` under `working-directory: backend`; build job = `docker compose build`. Guard lives in `tests/agent_protocol/test_ci_workflow.py` (not backend/tests — avoids conftest's import-time DB setup, and that dir is already collected by the contract command); needed `pyyaml==6.0.3` in the dev group, lock diff is exactly the two pyyaml metadata lines, no other pin moved. Manager falsified the guard 3 ways the done-when grep cannot catch, done-when staying exit 0 each time: drop `../tests/agent_protocol` → fail; drop `working-directory: backend` → fail; drop `pull_request:` → fail. AC1 re-run on a real fresh clone → exit 0, 26 passed; AC5 → exit 0; AC6 → exit 0; AC10 now genuinely clean (`.claude/` was only the harness worktree dir and vanished with `git worktree remove`, so the hazard carried since T01 is closed, not by a code change). **Known residual gap, confirmed by the manager by hand:** the guard's `"tests" in step["run"]` is implied by the `"../tests/agent_protocol"` check, so a CI command reduced to `uv run pytest ../tests/agent_protocol` — dropping the backend suite, AC1's whole point — still leaves all 3 guard tests green; token-matching (`step["run"].split()`) would close it. Other advisories: checkout@v4/setup-uv@v5 are mutable, non-latest majors (latest v7.0.1/v10.1.0, both pinned majors still node20); no branch filter or `concurrency` group, so a push to a branch with an open PR runs everything twice. Reviewer verified from the action definition that setup-uv@v5 does accept `python-version`, and that `uv run` self-syncs so the `uv sync` step is defensive rather than load-bearing; whether `docker compose build` works bare on ubuntu-latest could not be verified from this box and stays manual, as the contract already allows.
2026-09-17 — contract re-sealed (cc3579b8): AC4/AC5 verify lines and the dead-code key were malformed and ran as shell; work unchanged, T01–T06 verified
2026-09-18 — contract sealed (832d28dc): populated queue + GUI, 14 tasks, dead-code baseline 4 (vulture+knip), next T01

## 2026-09-17T23:12:35Z · T01 · verified
- attempt: 1 · model: sonnet · reviewer: opus
- commits: 6e343ae
- commands: done-when → exit 0 (vite 8.3.0, tree clean); test → exit 0 (26 passed, unchanged); probe: RED (4 config files reverted — .gitignore, Dockerfile, package.json, package-lock.json); dead-code → 3 (baseline 4, fell as the contract predicted)
- review: approve (1 advisory, pre-existing and out of scope — missing `frontend/.dockerignore`, filed as B9)
- notes: manager hand-falsified each done-when clause separately because the probe's RED only proved the first — lockfile moved aside → `npm ci` exit 1; Dockerfile reverted to `npm install` → grep exit 1; the three .gitignore lines deleted → 4 files dirty. `"latest"` resolved to big majors (vite 8, typescript 7, react 19) against an unchanged `frontend/src/`; reviewer proved `tsc -b` is live by injecting a type error (TS2322, build exit 1) and built the image from a clean `git archive` context under node:22-alpine/npm 10.9.8 → byte-identical bundle, so the npm-11-lockfile-on-node-22 worry is not real (lockfileVersion 3, both glibc and musl bindings present). Caret ranges are inert: `npm ci` is the only npm invocation in the repo and CI has no Node job. **Hazard for every later task:** `.claude/` is untracked and un-ignored, so a live agent worktree makes `git status --porcelain` non-empty and spuriously fails AC3 and this done-when — manager had to remove the worktree before verifying; filed as B8.

## 2026-09-18T00:00:00Z · T02 · attempt 1 rejected — repair dispatched
- attempt: 1 · model: opus · reviewer: not reached (manager verification failed first)
- commits: 30c7160 (reset out of the branch; preserved as tag `t02-attempt1-rejected`)
- commands: done-when → exit 1; test → exit 1; probe: RED (9 impl files reverted)
- finding: `backend/alembic/` makes setuptools flat-layout discovery see two top-level packages
  (`app`, `alembic`), so `magic-tower-api` fails to build and every `uv run`/`uv sync` under
  `backend/` exits 1 — `error: Multiple top-level packages discovered in a flat-layout`.
- notes: the worker's reported "done-when → exit 0 / 29 passed" was real when it ran but does not
  reproduce — it came from a uv build cache populated before `backend/alembic/` was scaffolded. The
  same failure reproduces in the worker's own worktree and on a fresh clone of 30c7160. Its
  `docker compose build` → exit 0 was green for an unrelated reason: `backend/Dockerfile:13` uses
  `uv sync --frozen --no-dev --no-install-project`, which never builds the project package, so the
  container path structurally cannot catch this. Manager confirmed the fix direction on a throwaway
  clone: adding `[tool.setuptools] packages = ["app"]` to `backend/pyproject.toml` gives done-when
  exit 0 and 29 passed. Everything else in the attempt (3 migration tests, the stamp path, the
  Dockerfile CMD) was never independently verified, because the build failure blocked verification.

## 2026-09-18T02:10:00Z · T02 · blocked(0001 skips-and-stamps on table names only, so a column-drifted legacy DB is marked migrated and left broken)
- attempt: 2 · model: fable · reviewer: opus
- commits: 9574426 (left merged — the tree is green and strictly ahead of base; see notes)
- commands: done-when → exit 0; test → exit 0 (31 passed, was 26); probe: RED (9 impl files reverted); dead-code → 3 (baseline 4)
- review: revise: `0001_initial_schema.py:37-43` keys skip-and-stamp on table names only, so a pre-Alembic DB whose `work_items` lacks `priority` is stamped `0001` and left unserviceable
- notes: attempt 1 (opus, 30c7160, tag `t02-attempt1-rejected`) was rejected by the manager before review — `backend/alembic/` tripped setuptools flat-layout auto-discovery, so every `uv run`/`uv sync` under `backend/` exited 1; its green commands came from a uv build cache populated before the directory existed. The repair fixed that with an explicit `[tool.setuptools] packages = ["app"]` and, notably, a *guard* for it: `backend/tests/test_packaging.py` builds a wheel against a tree carrying a deliberate stray top-level dir. Manager verified on a **fresh clone** this time (the check that caught attempt 1): done-when exit 0, 31 passed. Falsified independently, each on its own: `script_location` commented out → upgrade exit 255; bare `# note: ALTER TABLE` comment appended to `main.py` → grep clause exit 1; `priority` deleted from `0001` → drift test FAILED; `[tool.setuptools] packages` swapped for `packages.find include=["*"]` (a tree that still builds) → packaging test FAILED `{'app','stray'} == {'app'}`; `create_all` startup hook re-added → `test_application_startup_writes_no_schema_of_its_own` FAILED, which the done-when grep cannot catch. The worker's doubt that `test_a_database_holding_only_some_baseline_tables_is_refused` was never observed red is resolved — manager removed the `RuntimeError` branch and it reddened on its stderr assertion, so it distinguishes deliberate refusal from an incidental `OperationalError`. **The blocking defect, reproduced by the manager by hand:** create_all DB → `ALTER TABLE work_items DROP COLUMN priority` → `alembic upgrade head` exits 0, writes `alembic_version='0001'`, `priority` still absent. Before this diff the startup `ALTER TABLE` repaired that volume automatically. Population is narrow — `git log -S` confirms `priority` and the `ALTER TABLE` both arrived in `05bc7f3 Initial Magic Tower release`, so only a pre-initial-release dev volume can be affected — but the regression turns a self-healing path into a silent one, and README/Dockerfile document the false claim. Filed as B10/B11, with the stamp-only alternative as B12. **Commit left merged deliberately:** it is green on a fresh clone and satisfies AC4's verify command, so the next session should repair forward (make `_baseline_already_present()` column-aware) rather than rebuild the scaffold; T03 stays gated because its dep is not `verified`.

## 2026-09-18T00:25:00Z · T10 · attempt 1 rejected — repair dispatched
- attempt: 1 · model: sonnet · reviewer: opus
- commits: bfcc54d (reset out of the branch; preserved as tag `t10-attempt1-rejected`)
- commands: done-when → exit 0; test → exit 0 (31 passed); probe: RED but weak (reverting the 9
  impl files deletes the `test` script itself, so npm failed with `Missing script: "test"` — that
  RED proves only that no test script existed at base, nothing about the test's substance)
- review: revise — two blocking findings, both reproduced by the manager by hand
- finding 1: `@import "tailwindcss";` at `frontend/src/styles.css:1` pulls in Tailwind v4 preflight,
  whose `@layer base` carries `h1,h2,h3,h4,h5,h6{font-size:inherit;font-weight:inherit}`. App CSS is
  unlayered so it wins only for properties it declares, and **no rule in `styles.css` declares
  `font-weight` on any heading** — so every heading in the GUI renders at 400 instead of bold. The
  same preflight strips `.sync form input` (the LOCAL_API_TOKEN unlock field, whose only rule is
  `{width:100%;margin-top:12px}`) of its border, padding and background.
- finding 2: build is no longer reproducible. Tailwind v4 auto source detection scans the build
  context and cannot see the root `.gitignore` (there is no `frontend/.gitignore`, no
  `.dockerignore`, and `Dockerfile:5` is `COPY . .`), so it scans a stale `dist/` when one is
  present. Manager measured both, same commit and lockfile: `dist/` in context → 14,437-byte
  `index-AfK56yVL.css`; clean `git archive` context → 11,594-byte `index-BAvVTd-x.css`. This is
  backlog B9 (filed as cosmetic by the T01 reviewer) turned load-bearing, and it undoes T01's point.
- notes: everything else checked out and should be preserved in the repair — the App extraction is
  byte-identical bar `export default` (reviewer diffed it mechanically), pinning is clean with no
  `"latest"` and lockfile floors matching exactly, peer ranges all satisfied against vite 8 /
  ts 7 / react 19, dead-code held at 3, fresh-clone `npm ci` + test + build all exit 0, and `"DOM"`
  in `tsconfig.node.json` is genuinely required (removing it fails `tsc -b` with TS2304
  `DOMHighResTimeStamp` via `vitest/config` → tinybench). The test is real: manager gutted the
  offline-fallback branch and it reddened. Reviewer confirmed the worker was boxed in on touching
  `styles.css` — dropping the `@import` entirely makes knip report `tailwindcss` an unused
  devDependency, pushing the gate 3 → 4; the fix is to import `tailwindcss/theme.css` +
  `tailwindcss/utilities.css` (utilities without preflight), not to drop Tailwind.

## 2026-09-18T00:45:00Z · T10 · verified
- attempt: 2 · model: opus · reviewer: opus
- commits: ab5ec9b
- commands: done-when → exit 0; test → exit 0 (31 passed); probe: RED but vacuous-by-construction (see notes); dead-code → 3 (baseline 3)
- review: approve (3 advisories, all T11-absorb — filed as B13/B14/B15)
- notes: attempt 1 (sonnet, bfcc54d, tag `t10-attempt1-rejected`) was rejected on two blocking findings; the repair delta is exactly 3 files, with `App.tsx` and `package-lock.json` byte-identical to attempt 1, so the verified parts were reused rather than rebuilt. **The probe is structurally useless for this task and will be for T11–T13 too:** reverting the impl files deletes the `test` script itself, so it fails with `Missing script: "test"` — RED that proves only that no test existed at base. Both times the real proof was hand falsification. Fix 1, preflight: `@import "tailwindcss"` → `tailwindcss/theme.css` + `tailwindcss/utilities.css`; manager verified on the built CSS (7,455 B, was 11,594 B) that zero `@layer` blocks, no `h1..h6{font-weight:inherit}`, no universal `border:0 solid` and no preflight markers survive while `.brand h1`/`.detail h3`/`.sync form input`/`.sync button` all do. Reviewer confirmed the split is public API in tailwindcss@4.3.3's `exports` map, that variants/`@media`/theme tokens still compile, and — the thing I most doubted — that v4's `.border` utility is self-sufficient (`@property --tw-border-style` with `initial-value:solid`), so shadcn no longer depends on preflight the way it did in v3. Re-adding preflight later as `layer(base)` is additive and cannot regress today's CSS. Fix 2, reproducibility: `frontend/.dockerignore`; manager built the image twice from the same commit — `dist/` present → 7,455 B, clean `git archive` context → 7,455 B, identical, where before the fix the same test gave 14,437 B vs 11,594 B. Closes B9, which the T01 reviewer had filed as cosmetic and which T10 turned load-bearing. Fix 3 was the tightened assertion, and it is not cosmetic: breaking only `setSelected(demoItems[0])` (list populated, detail pane empty) fails `toHaveLength(2)` and **passes** the old `.not.toHaveLength(0)` — manager ran both against the identical mutation. Also verified: fresh-clone `npm ci` + done-when + build all exit 0 with identical CSS hash; `"DOM"` in `tsconfig.node.json` is required (TS2304 `DOMHighResTimeStamp` via tinybench without it); no `"latest"`, lockfile floors match carets exactly. **For T11:** it inherits an unlayered utility layer (better than the umbrella, where layered utilities lose to *every* unlayered app rule including bare `button{}`), and must handle B13 before copying components in or the first shadcn button will render invisible.

## 2026-09-18T01:10:48Z · T11 · verified
- attempt: 1 · model: opus · reviewer: opus
- commits: 238d022
- commands: done-when → exit 0 (4 passed, 1 skipped); test → exit 0 (31 passed, unchanged); frontend suite → exit 0 (5 passed); probe: RED (20 impl files reverted); dead-code → 3 (baseline 3)
- review: approve (2 advisories, both filed — B16 unlock clears the token field on a failed unlock, B17 package.json re-sort churn)
- notes: first attempt verified, no repair round. **The probe finally bit on this task** — T10's note predicted it would stay structurally vacuous for T11–T13, and that prediction was wrong: reverting the impl no longer deletes the `test` script (T10 committed it), so the revert reddened on real assertions (`Unable to find role="region" and name "Filters"`, `Unable to find a label with the text of: Local API token`) rather than `Missing script`. Manager reproduced by hand before trusting the verdict. Separately the done-when **was** a vacuity trap at base: `npm run test -- --run -t "layout"` exits 0 with "1 skipped, 0 run" when nothing matches the `-t` filter, so a worker who named no test "layout" would have passed it green — it now selects 4 real tests, and a deleted `<ResizableHandle />` reddens it. Reviewer ran 4 independent mutations, each reddening a different test, including falsifying **both** arms of the `401 || 503` compound gate separately. Adjudicated and dismissed: the worker restored the full `@import "tailwindcss"` whose preflight de-bolds `h1..h6` — the exact mechanism that blocked T10 attempt 1 — but with 0 legacy selectors surviving there is nothing left to de-bold, and the five serif headings are consistently 400 while the two sans ones are consistently `font-semibold`; a system, not a leak. B13/B14/B15 all closed and verified mechanically on the built CSS (`.bg-primary` emits rules, preflight present, 0 legacy selectors). Build reproducibility re-checked with and without a stale `dist/` — byte-identical CSS, T10's `.dockerignore` holding. Worker's `frontend/src/test-setup.ts` stubs ResizeObserver/scrollIntoView (genuine jsdom gaps for react-resizable-panels and cmdk); reviewer confirmed it hides nothing. shadcn's published `resizable.tsx` targets react-resizable-panels v2/v3 and will not compile against the v4 API here — this one is hand-adapted, so do not paste the upstream file in T12/T13. Status `<select>` left native and every shadcn file trimmed to what is rendered, both to hold the knip gate at baseline; a later task wanting `buttonVariants` or `CommandShortcut` must add them at point of use or the gate rises.

## 2026-09-18T03:05:00Z · T02 · attempt 1 rejected — repair dispatched
- attempt: 1 · model: opus · reviewer: not reached (manager verification failed first)
- commits: a97bcb6 (never merged; preserved as tag `t02-attempt1-selector-miss`)
- commands: done-when → **exit 5**; test → exit 0 (34 passed); probe: RED but noisy (13 files reverted, 10 of them irrelevant frontend/`.companion` churn from the wrong base)
- finding: **`-k alembic_stamp` selects zero tests.** All seven tests in
  `backend/tests/test_migrations.py` are named `test_a_database_…` / `test_upgrading_…`; none
  contains the substring `alembic_stamp`, so clause 1 of the done-when collects nothing and pytest
  exits 5 (`21 deselected`, no `passed` line). The task body requires the three cases to be
  selectable by `-k alembic_stamp`. `git grep alembic_stamp` finds nothing at base either, so the
  previous session's recorded "done-when → exit 0" for 9574426 could not have been true — the gate
  has never once selected a test.
- finding: worker reset onto **9574426, not the named base f860b3a** (it reported the worktree
  started at 05bc7f3 and reset to the wrong commit), so its branch is not fast-forwardable and every
  measurement it took ran against the pre-T10/T11 frontend. Its dead-code number is unusable for
  that reason: measured 5 here, but the Python side is 2 (the two known `config.py` `cls` false
  positives, unchanged) and the 3 extra are stale-frontend knip noise on files the worker never
  touched. No real regression, but it has to be re-measured after a merge onto the right base.
- notes: **the substance is right and must be preserved, not rebuilt.** Manager verified the owner's
  requirement by hand, both cases independently: matching legacy `create_all` DB → `upgrade head`
  exit 0, `alembic_version='0001'`; same DB with `ALTER TABLE work_items DROP COLUMN priority` →
  exit 1, `RuntimeError: database holds every baseline table but work_items is missing ['priority']`,
  and `alembic_version` left **empty** rather than stamped. That is B10 closed. Clauses 2 and 3 of
  the done-when pass on their own (fresh `/tmp` DB upgrade → exit 0; `ALTER TABLE` grep → exit 0),
  so clause 1 is the only failure. Full suite 34 passed (was 31). README:55-61 and Dockerfile:22-24
  both reworded for B11. Worker's own doubt, worth passing on: `BASELINE_COLUMNS` duplicates the
  `create_table` DDL beside it, guarded by
  `test_the_baseline_columns_the_skip_check_trusts_are_the_ones_it_creates`; and the check compares
  column **names only**, so a retyped column still stamps — backlog, not this task.

## 2026-09-18T03:55:00Z · T02 · verified
- attempt: 2 · model: fable · reviewer: opus
- commits: 65d6020, 027fdf2
- commands: done-when → exit 0 (**6 passed, 15 deselected**); test → exit 0 (34 passed, was 31); probe: RED (3 impl files reverted); dead-code → 3 (baseline 3)
- review: approve (3 advisories, all filed — B21 docs overstate the check, B22 guard test coupled to head-level `MODEL_TABLES`, B23 name-only comparison recorded as deliberate)
- notes: attempt 1 (opus, a97bcb6, tag `t02-attempt1-selector-miss`) was rejected by the manager
  before review on two findings, both mine: it reset onto **9574426 instead of the named base**, so
  every number it reported came from a tree without T10/T11; and **`-k alembic_stamp` selected zero
  tests** — all seven names were `test_a_database_…`, pytest exited 5 on `21 deselected`, and
  `git grep alembic_stamp` found nothing at base either, so the gate had *never once* selected a
  test and the previous session's recorded "done-when → exit 0" for 9574426 cannot have been true.
  The repair was therefore a cherry-pick of the correct substance onto the right base plus 6 renames
  — `git diff` is 4 files, +153/−15, nothing else. Each clause of the compound done-when falsified
  **separately**, because a RED on an `&&` chain proves only what short-circuited: clause 1,
  `_column_drift`'s loop neutered to `{}.items()` → 2 failed (`…lost_a_column`, `…gained_a_column`);
  clause 2, `script_location` commented out → upgrade exit 255; clause 3, `# probe: ALTER TABLE`
  appended to `app/main.py` → exit 1. All restored clean. The owner's requirement checked by hand in
  the main tree: legacy `create_all` DB with `priority` dropped → exit **1**, `RuntimeError: database
  holds every baseline table but work_items is missing ['priority']`, `alembic_version` rows `[]`,
  column still absent; matching legacy DB → exit 0, `alembic_version='0001'`. B10 closed. The
  reviewer earned its keep on the question I could not answer by running commands — **over-refusal**
  — by building seven legitimate DB shapes (pristine legacy, legacy healed by the old startup DDL,
  extra table, extra index, a view, already-stamped, offline `--sql`), all of which still stamp, and
  by AST-diffing `BASELINE_COLUMNS` against the `create_table` calls column by column (35 columns,
  zero divergence) rather than trusting the worker's guard test — then breaking that guard two ways
  the worker had not tried. **Its most useful finding is the inverse of the original bug:** the old
  self-healing `ALTER TABLE` added `priority` as `VARCHAR(6) NOT NULL DEFAULT 'medium'` with no enum
  CHECK, so a *definition*-level check would refuse the most likely real volume in existence and
  crash-loop the container CMD. Name-only is correct; only the docs oversell it (B21). Two traps
  worth carrying forward: the worker's dead-code "9" was knip run **without `node_modules`** in its
  worktree — the real number is 3, and knip's half must be measured where deps are installed; and
  the companion Bash guard **blocks this task's own done-when** (its `rm`-plus-`tests` patterns both
  match), so the chain was run verbatim from a script file rather than skipped — filed as B24.
  `.claude/` is still untracked and un-ignored, an AC10 hazard for a later task.

## 2026-09-18T11:42:00Z · T03 · verified
- attempt: 1 · model: opus · reviewer: fable
- commits: 636eb61
- commands: done-when → exit 0 (**1 passed, 27 deselected**); test → exit 0 (41 passed, was 34); probe: RED (6 impl files reverted); dead-code → 3 (baseline 3, node_modules present)
- review: approve (one advisory, filed as B25 — `WorkEvidence.excerpt` still cleartext)
- notes: Sealed in the column type (`EncryptedText` TypeDecorator, `backend/app/services/field_crypto.py`)
  rather than at call sites, so every writer of `Source.excerpt` is covered by construction and every
  reader still sees cleartext; AAD is `b"workboard-source-excerpt-v1"`, deliberately not the token
  store's `b"workboard-graph-v1"`, same `APP_ENCRYPTION_KEY`, no second key. Column stays `TEXT`, no
  column added or renamed, so T02's name-based `BASELINE_COLUMNS` check needed no update and stays
  honest — reviewer confirmed. Missing/unopenable key fails closed to 503 via a stacked
  `@app.exception_handler(FieldEncryptionError)` + `(StatementError)` that re-raises anything else;
  reviewer verified by running that stacking two decorators really does register both and that a
  non-encryption `StatementError` still reaches a 500. Data revision `0002` is re-runnable: a value
  already carrying the `aesgcm.v1:` prefix is decrypted as a check and skipped, and a prefixed value
  that will NOT open aborts the migration loudly rather than double-sealing — same posture as `0001`
  towards drift. Reviewer went past the worker's re-run test to the shapes it had not built: migration
  with no key and rows present → rc 1, rows untouched, version stays at `0001`; fresh no-key
  `upgrade head` on zero rows succeeds; 400 legacy rows migrated with 0 plaintext residue in the file.
  **Behaviour change worth carrying:** `alembic upgrade head --sql` (offline) now exits 1 at `0002`
  with "encrypting source excerpts needs a live database" — a data migration cannot be expressed
  offline, and emitting the values as literals would write the very cleartext this revision removes
  into a script on disk. Nothing in the repo uses `--sql`; the alternative was a silent skip.
  Two numbers that looked like disagreements and were not: the reviewer reported "28 passed" against
  my 41 — it had run `pytest tests -q` without `../tests/agent_protocol`; both agree on +7 new, and I
  re-ran both commands side by side (28 and 41) rather than take either on faith. And vulture first
  read 10, not 3, because six unused `encryption_key` fixture params and two `dialect` params were
  real findings — the worker fixed them (`@pytest.mark.usefixtures`, `_dialect`) instead of moving the
  baseline. knip was measured with `node_modules` installed, per the T02 lesson. The dead-code chain
  is still blocked by the companion Bash guard (B24), so I ran it verbatim from a script file again.
  Out of scope and filed rather than widened: **B25** — `WorkEvidence.excerpt` is still plain `Text`
  and `routes.py:121` copies evidence excerpts into `agent_dispatches.instruction`. The worker raised
  it, the reviewer reproduced it (marker visible in raw file bytes after `POST .../evidence`), and it
  matters more than it sounds: it is `WorkEvidence.excerpt`, not `Source.excerpt`, that the GUI
  blockquote renders, and **T05 is the task that starts carrying real mail into that column**. The
  contract's "mail and chat content stops sitting in plaintext on disk" is, as of today, true only of
  `sources`. T05 should close it or the owner should say it may stay open.

## 2026-09-18T12:31:00Z · T04 · verified
- attempt: 1 · model: sonnet · reviewer: opus
- commits: e2ee8f9
- commands: done-when → exit 0 (**3 passed, 28 deselected**); test → exit 0 (44 passed, was 41); probe: RED (2 impl files) but judged weak — falsified by hand instead; dead-code → 3 (baseline 3, node_modules present)
- review: approve (4 advisories + 1 naming caveat, filed as B26–B30; none blocking)
- notes: The probe's RED was not worth the letter it printed. It reverted both impl files, and one of
  them (`sync_registry.py`) is a *new module*, so the suite died at collection with ImportError —
  which proves only that deleting a module breaks imports. I falsified by hand instead: reverted
  **only** `backend/app/services/sync.py` to base, left the registry module in place, and got
  `2 failed, 1 passed, 28 deselected` with `TypeError: sync() got an unexpected keyword argument
  'kind'` on both. So two of the three selected tests are load-bearing on this task's behaviour. The
  third, `test_per_source_dispatch_defaults_to_graph_when_no_kind_given`, **passes at base** — it
  asserts `pytest.raises(SyncError, match="Microsoft Graph is not configured")`, already true before
  the change. Honest as a default-routing regression guard, but it is not evidence for AC6, and a
  future reader counting "3 passed" should know only 2 of them prove anything.
  **The worker deviated from the plan text and was right to.** The task says "a registry keyed by
  `SourceKind`"; it shipped a plain `str` key. I checked the enum myself rather than take either
  side's word: `SourceKind` is `outlook_email`/`teams_message`/`manual` (`backend/app/models.py:26-29`),
  a per-signal DB type, and one Graph connection emits *both* of the first two in a single
  `fetch_signals` call. Keying a connector registry on it would need two entries pointing at one
  handler and would make `sync(kind=SourceKind.outlook_email)` also fetch Teams messages. Jira and
  Freshservice — the kinds the contract's Result actually names — are not enum members at all. The
  reviewer reached the same conclusion independently. Plan text was loose; the code is right. Cost:
  a third vocabulary for "kind" (B30).
  Registry is real, not theatre — both reviewer and I checked the thing most likely to be fake: the
  fake kind registers through the public API and syncs end to end with **zero** edits to `sync()`'s
  body. Graph identity assertion survived the extraction intact and now lives only in `_sync_graph`
  (`sync.py:49-51`), so no other kind can trigger it — which is exactly what the task asked.
  One finding I want to flag louder than "advisory": **B26**, `registered_kinds()` is dead on
  arrival, zero call sites, introduced by this task. The contract's quality bar says "no dead code",
  but the sealed gate runs vulture at `--min-confidence 80` and this only surfaces at 60 — so the
  gate reported 3, baseline 3, green, while genuinely dead code went in. The gate is not lying, it is
  just tuned below this. Worth deleting in the next task that opens the file (T05 does not), and
  worth remembering that a green dead-code number is a floor, not a proof.
  Also still open and not mine: `.claude/` remains untracked and un-ignored (B8), so AC3 and any
  `done-when` ending in `test -z "$(git status --porcelain)"` fail spuriously while a worktree is
  live. I removed the worktree before the final checks, as the T01 manager had to.

## 2026-09-18T14:05:00Z · T05 · attempt 1 findings (reset to base, repairing)
- attempt: 1 · model: opus · reviewer: fable (author was opus; reviewer must not be the author's model)
- commits: 331b586 (kept on `worktree-agent-a2214a10cdb7ebae2`, not merged into main)
- commands: done-when → exit 0 (14 passed, 31 deselected); test → exit 0 (58 passed, was 44); dead-code → 3 (baseline 4); AC5 → exit 0; AC4 chain applies through 0003
- review: revise — rule 3's bulk-header clause ships green when deleted; no fixture reaches it
- notes: Attempt 1 was good work that failed on one falsifiable gap, so the reset is not a
  judgement on the rest. The scripted probe printed RED but reverted 6 files including the new
  `promotion.py`, so it only proved that deleting a module breaks collection — same vacuous shape as
  T04. I falsified by hand in seven scenarios instead; 13 of 14 selected tests are load-bearing.
  The hole the reviewer found, which I then confirmed myself and found to be wider than reported:
  `_is_bulk_mail` has **three** clauses and only one is pinned. Deleting the
  `List-Unsubscribe/List-Id/List-Post/X-Campaign-Id` clause → 14 passed. Deleting the
  `Precedence: bulk|list|junk` clause → 14 passed. Only the `Auto-Submitted` clause reddens anything.
  The reason is that the one newsletter fixture sends from `newsletter@vendor.example`, so rule 2
  (automated-sender local part) rejects it before rule 3 is ever consulted — and the sync-path
  fixture uses the same sender. Worse, the test *named*
  `test_promotion_skips_bulk_mail_whose_only_marker_is_a_precedence_header` asserts
  `auto-submitted: auto-generated` and never sets `precedence` at all; its name describes a case the
  suite does not cover. This is load-bearing for AC7's "ignores noise": the worker's own docstring
  justifies keeping rule 2's marker list short ("leaves `info@`, `news@`, `updates@` alone") on the
  grounds that rule 3's headers catch those — and that is precisely the half no test holds.
  Two more unpinned bodies found by the reviewer and confirmed: `_source_url` can `return None`
  outright with 14 still green. Filed for the repair, not blocking on their own.

## 2026-09-18T15:40:00Z · T05 · blocked(Graph→signal normalization feeding rules 1, 2 and 4 is unpinned: `_address`, `_addresses`, `toRecipients` in the `$select`, and `_teams_sender_kind` can each be stubbed with all 87 tests green)
- attempt: 2 · model: fable · reviewer: opus (attempt 1: opus, reviewer fable — a reviewer must never be the author's model)
- commits: 0dd793a (merged, green, left in the tree); 331b586 (attempt 1, reset away, branch deleted)
- commands: done-when → exit 0 (43 passed, 31 deselected); test → exit 0 (87 passed, was 44); probe: RED but VACUOUS both attempts — falsified by hand instead; dead-code → 3 (baseline 4); AC4/AC5/AC6 → exit 0
- review: revise: `_address` (`backend/app/services/graph.py:23-27`) can return `None` for every Graph row with the full suite green, so rule 2 never fires in production and every newsletter lands in the queue
- notes: **The block is not a verdict on the code, which is good and is merged.** It is that AC7's
  "ignores noise" is still not provable. Attempt 2 fixed exactly what it was sent back for: I deleted
  each clause of `_is_bulk_mail` myself and got 6 failed (List-*/X-Campaign-Id), 3 failed
  (Precedence), 2 failed (Auto-Submitted), and the test names now state what they assert
  (`..._skips_a_human_looking_sender_whose_only_marker_is_a_list_header[List-Id]`). The 43 tests are
  honest — the reviewer checked for padding and found none, and the parametrization is one distinct
  rejected input per case.
  What neither attempt pinned is one layer lower: the *decision function* is tested exhaustively with
  hand-built dicts, but the *wiring* that turns a Graph row into such a dict is tested by nothing. I
  reproduced all four myself against the full 87-test suite, each edit asserted to have applied:
  `_address` → `return None` → 87 passed. `_addresses` → `return []` → 87 passed. Delete
  `toRecipients` from the `$select` (`backend/app/integrations/graph.py:46`) → 87 passed.
  `_teams_sender_kind` → `return "user"` → 87 passed. So two of the task's three named rules ("skip
  automated/newsletter senders", "promote signals addressed directly to the user") have zero coverage
  from the shape Graph actually returns, and rule 1 has none either. It is the same failure class as
  attempt 1 — a fixture that never reaches the code it is supposed to pin — one level down, which is
  why I did not treat it as advisory.
  **The fix is small and known**, which is the argument for one more session rather than a redesign:
  the e2e `INBOX` fixture (`backend/tests/test_promotion.py:357-371`) needs a `newsletter@` row
  carrying no bulk headers, a cc-only row whose `toRecipients` is someone else, and a chat row with
  `from.application`; then assert `new_work_items` stays 1. Both reviewers converged on that.
  Two numbers that looked like disagreements and were not: the attempt-2 reviewer reported "74
  passed" against my 87 — it ran `pytest tests` without `../tests/agent_protocol` (87 − 13). And my
  own first `_source_url` probe printed "43 passed" while proving nothing: I had written a regex
  against `-> str | None` when the signature is `-> HttpUrl | None`, so the file never changed. Every
  probe above re-ran with an assertion that the edit actually applied. A probe that cannot fail is
  worse than no probe, because it reads like evidence.
  Carried out of scope rather than dropped: B31 (`_source_url` positive case unpinned — both
  reviewers rated it advisory and it is *not* what this is blocked on), B32 (`Collection[str]` accepts
  a bare `str` and iterates it per character), B33 (Teams: the owner's own posts and system events
  promote), B34 (`internetMessageHeaders` under `$select` on the list endpoint is unverified against a
  live tenant — if Graph ignores it, rule 3 never fires in production and rule 2 is the only defence).
  B25's first half is closed by this work: `WorkEvidence.excerpt` is `EncryptedText` under its own AAD
  with re-runnable revision `0003`; the reviewer checked the AAD separation, the mixed-table case and
  `downgrade`. B25's second half (`agent_dispatches.instruction`) stays open, as does B26.

## 2026-09-18T17:05:00Z · T05 · verified
- attempt: 1 · model: opus · reviewer: fable (author was opus; a reviewer is never the author's model)
- commits: 90dafc9
- commands: done-when → exit 0 (43 passed, 31 deselected); test → exit 0 (87 passed); probe: INAPPLICABLE (test-only) → falsified by hand, 5/5 RED; dead-code → 3 (baseline 4)
- review: approve — each noise row is rejected by exactly one rule, so no rule masks another
- notes: The block is closed. The diff is test-only (+46/-3, `backend/tests/test_promotion.py`); the
  promotion implementation from attempt 2 was already merged and was not touched. I re-ran all four
  named stubs myself in the worktree, each with the edit asserted to have landed on disk and asserted
  restored afterwards: `_address`→None RED, `_addresses`→[] RED, `toRecipients` dropped from the
  `$select` RED, `_teams_sender_kind`→"user" RED. The worker's extra fifth, `_headers`→{}, is also
  RED, so the whole Graph→signal boundary is load-bearing, not just the four the block named.
  Because the diff is test-only, that reddening can only come from the new fixture. I also ran a
  **negative control** the block did not ask for: a behaviour-preserving rewrite of `_address`
  (unwrap via an intermediate local) left the suite GREEN. That rules out the failure mode where a
  test reddens on any edit to the file and so proves nothing — the reason two earlier attempts
  produced evidence that read stronger than it was.
  The fixture is three new noise rows (`newsletter@` with no bulk header, a cc-only row addressed to
  someone else, a `from.application` chat post) and `new_sources` 2→5, which is a strengthening: it
  proves every noise row reached the heuristic instead of being dropped before it. The reviewer
  traced each of the four URLs `GraphClient` really builds through the fake and confirmed
  `_selected` serves only `$select`ed fields, and checked that each noise row is rejected by exactly
  one rule (bulk→r3, newsletter→r2, cc-only→r4, bot-post→r1) so a regression in one is not masked by
  another. `test_promotion_is_idempotent` untouched.
  Carried to the backlog rather than dropped: B35 (the fake dispatches on `"/me/chats"` before the
  messages branch — wrong-reason-but-loud, not a silent pass). B31–B34 from the blocked session
  remain open and were re-confirmed as still out of scope here; B25's second half
  (`agent_dispatches.instruction`) and B26 also still open.
  Worker note worth keeping: its worktree started at `05bc7f3` (`main`), not the run branch — the
  known failure mode. It reset to base before working and every number above is from `1f1d6cd`.

## 2026-09-18T18:20:00Z · T06 · attempt 1 findings (repair dispatched)
- attempt: 1 · model: sonnet · reviewer: opus
- commits: a12fe1f (reset away, preserved on `worktree-agent-a23f8e11c4ed0f2f5`)
- commands: done-when → exit 0 (6 passed, 74 deselected); test → exit 0 (93 passed); probe: RED; dead-code → 3 (baseline 4)
- review: revise — backfill promotes every un-promoted `Source`, including ones the live heuristic
  already rejected, so calling the endpoint after a normal sync injects newsletter/no-reply noise.
- notes: All the mechanical gates were honest and I re-ran each one myself. The probe was RED
  behaviourally, not by ImportError: I stubbed the body to `return 0` with the symbol left
  importable and got 4 assertion failures, 2 passes (empty-table and auth-401, which legitimately
  should not be sensitive), restored byte-exact, and ran a negative control (behaviour-preserving
  rewrite) that stayed GREEN. So the tests do pin behaviour — they just pin the wrong scope.
  The defect is the selection predicate, not the plumbing. `backfill_promoted_sources` selects
  "every `Source` with no matching `WorkItem`", which has no time bound, while its own docstring
  claims "rows written before this module existed". I reproduced the gap end to end myself:
  a `noreply@vendor.com` signal carrying `List-Unsubscribe` → live `promote_signals` creates 0 work
  items, `persist_signals` stores the `Source`, then `backfill_promoted_sources` creates 1 work item
  titled "Weekly newsletter". The endpoint is permanently mounted and re-callable, so this is not a
  one-time migration hazard. Six fixtures are all bare `Source(kind, external_id, subject)` rows —
  exactly the shape where the correct and the buggy implementation agree — so nothing could catch it.
  Verified non-findings, so the repair does not churn them: the anti-join id spaces really do match
  (`persist_signals` and `_work_item` both write `str(signal["external_id"])` with the same
  `outlook:`/`teams:` prefix), and the `source_external_id.is_not(None)` guard is load-bearing —
  without it one manual work item with a NULL external id makes `NOT IN` evaluate to NULL and
  backfill returns 0 forever. Endpoint auth/CSRF and envelope match `POST /api/sync`.
  The worker's own doubt is real but separate and is *not* what this is blocked on: `Source` never
  stored `sender`/`sender_kind`/`headers`/`to_recipients`, so rules 1-4 cannot fire on a genuinely
  pre-T05 row. Confirmed against `models.py` — the columns do not exist. That is a permanent data
  gap, not a code defect, and the contract's answer to it is the owner's manual dismiss (T08).
  Carried to the backlog rather than dropped: B36 (`DELETE /api/work-items/{item_id}` already exists
  at `routes.py:43`, so backfill resurrects any hand-deleted item — live on this branch today, not a
  future T08 concern), B37 (`owner_addresses` is inert on the backfill path and no caller passes it),
  B38 (the empty-table test's docstring claims it pins the cheap `LIMIT 1` path, but deleting that
  early return leaves it green, so "must not slow boot on an empty DB" is unpinned).

## 2026-09-18T21:05:00Z · T06 · blocked(queue-level gate silently disables the backfill after the first promoting sync, so the pre-T05 sources the task exists for are never promoted)
- attempt: 2 · model: opus · reviewer: fable (opus authored the repair, so the reviewer must differ)
- commits: dd306f9 (reset away, preserved on `worktree-agent-aa02c3e50aa3ca413`)
- commands: done-when → exit 0 (6 passed, 74 deselected, main tree); test → exit 0 (93 passed, was 87 at base); probe: RED but vacuous; dead-code → 3 (baseline 3)
- review: revise — the queue-level gate satisfies AC8 only under an unenforced "backfill before any sync" ordering and silently disables itself otherwise
- notes: Every mechanical gate was honest and I re-ran each myself, but the probe's RED is worthless
  here and I did not treat it as evidence: reverting `promotion.py` deletes the symbol `sync.py`
  imports, so it reddens by ImportError. The real falsification is by hand and it does hold — Stub B
  (attempt 1's per-source anti-join predicate swapped back in) reddened **exactly one** test,
  `test_backfill_leaves_a_source_the_live_heuristic_declined_unpromoted` with `assert 1 == 0`, and a
  behaviour-preserving negative control stayed GREEN at 6 passed; restored byte-exact both times
  (md5 `28d156a0…`). So attempt 1's blocking finding is genuinely fixed and that discriminator is a
  real test built through `persist_signals`/`promote_signals`, not bare `Source` rows. **The new
  blocking defect, which I reproduced by hand before the review and the reviewer then reproduced
  independently:** store two pre-T05 sources with an empty queue, run one ordinary sync that
  promotes one signal, then call the backfill → `created: 0`, queue holds only the fresh item, the
  two pre-T05 rows are unreachable forever and the endpoint answers `{"new_work_items": 0}`, which
  is indistinguishable from "nothing to do". Nothing in the code, the README (`:109` documents
  `/api/sync` only) or the frontend (`api.ts:36`) establishes a backfill-before-sync ordering, so
  sync-first is the default, not a contrived path. This is the T02 failure shape the owner already
  blocked once — a loud path turned silent. Root cause is structural and both attempts hit different
  faces of it: a `Source` stores neither sender, headers nor recipients, so "unpromoted" cannot
  distinguish *never judged* from *judged and declined*, and no predicate over existing state can.
  The fix both reviewers converged on is in plan.md: a durable per-source judgement marker written
  by `promote_signals` for every signal it decides. **The worker rejected that fix on a claim that
  is half false** — it said a `promotion_checked_at` column *and* a new table both break T02's stamp
  test. The column half is true (`test_migrations.py:135,164,178` build their legacy DB from today's
  models, so `0001`'s frozen `BASELINE_COLUMNS` drift check refuses); the table half is false,
  because `0001`'s skip check is scoped to `BASELINE_COLUMNS.keys() & get_table_names()` and an
  added table is invisible to it. I verified that empirically rather than on either agent's word.
  **Commit reset away, unlike T02's block:** the defect here *is* the predicate and the tests that
  pin it, and the recommended design deletes `backfill_queue_from_sources` and its direct
  `create_work_item` call, so repairing forward would mean repairing against a design the review
  discards. Nothing is lost — it is on its branch, and its fixtures are worth cherry-picking.
  **An interrupted earlier session left a real head start.** A repair worker dispatched before this
  one never reported (its session ended mid-flight) and I did not merge or trust its work, but the
  reviewer found its worktree and I verified it myself: it implements the `source_promotions` marker
  via revision `0004` and is green at 98 passed, `test_migrations` 7, `-k backfill` 11. I committed
  it unreviewed as `4db5567` on `worktree-agent-a2af9b2b1c1e76c3e` so it survives worktree cleanup.
  It is a lead, not an endorsement — nobody has reviewed that diff.
  Carried to the backlog rather than dropped: B39 (T02's three legacy-DB tests build the pre-Alembic
  database from live models, so they block *every* future column, not just T06's — with the
  reviewer's concrete fix) and B40 (no operator-facing docs for the backfill endpoint). B36–B38 from
  attempt 1 stay open; B36 is now partly confirmed as live — after a sync, hand-deleting the
  promoted item makes attempt 2's gate open again and backfill promotes the declined newsletter too,
  which the reviewer reproduced.

## 2026-09-18T11:32:08Z · T09 · blocked(the documented `docker compose` export path dies on a fresh second PC — `docker compose cp` into a not-yet-created `~/.magic-tower` exits 1, the same pasted-command-fails class the first review already blocked on)
- attempt: 2 · model: opus · reviewer: fable (opus authored the repair, so the reviewer must differ)
- commits: 8f72654, cc2a177 — **kept merged, not reset away**
- commands: done-when → exit 0; test → exit 0 (125 passed, 110 at repair base, 97 at task base); probe: RED but vacuous (attempt 1) / weak (attempt 2); dead-code → 3 (2 Python `cls` false positives + 1 TS, baseline 4)
- review: revise — `docker compose cp api:/data/labeled-sample.json ~/.magic-tower/labeled-sample.json` (README:133) fails `invalid output path: directory "/home/<you>/.magic-tower" does not exist` on any machine that has never run the export, which is the fresh-clone state by definition
- notes: **Kept merged, unlike T06, and deliberately.** Both reviewers endorsed the design — the two
  commands, `SourceSignalContext`, revision `0004`, the `persist_signals` carry-across, the header
  allowlist and the tests are all sound and independently verified. What is left is one README line
  on one of two documented run paths. Resetting would throw away work two reviews approved to fix a
  docs gap, so the next session repairs forward from `cc2a177`, it does not start over.
  **The exact remaining work, in order:** (1) add `mkdir -p -m 700 ~/.magic-tower` before the
  `docker compose cp` line at README:133 — the export tool's own `mkdir(mode=0o700)` runs *inside
  the container* on that path, so the host directory is never created and README:137's "writes the
  file 0600 under a 0700 directory" is also false there; (2) make `test_documented_commands.py`
  actually guard the compose path — it cannot see this today, which is why a docs-shaped test passed
  over a broken pasted command; (3) advisory: `heuristic_sample.py:86` `path.read_text()` has no
  `encoding`, so a non-UTF-8 locale (Windows cp1252 — plausible on the second PC) turns a subject
  containing `Á` into a `UnicodeDecodeError` traceback; (4) advisory: `heuristic_export.py:73`
  catches only `OperationalError`, so a Postgres URL at an unmigrated database still raises a raw
  `ProgrammingError` — low weight, the project is SQLite-only today.
  **I reproduced the blocking finding myself with a negative control** rather than taking the
  reviewer's word: `docker cp` into a missing host directory exits 1, into an existing one exits 0.
  I also reproduced the *first* review's blocking finding before ordering the repair, and confirmed
  the repair fixed it — the previously-crashing export command now prints two actionable lines and
  exits 1 instead of a 40-line traceback, and the documented uv sequence (`alembic upgrade head`
  0001→0004, then the export) runs clean on a fresh database and writes `-rw-------`.
  **The probe proved nothing both rounds and I did not treat it as evidence.** Attempt 1's RED is a
  collection error: reverting the 10 impl files deletes the module the new tests import. The real
  evidence is hand-falsification — attempt 1: seven stubs (precision arithmetic, recall arithmetic,
  malformed-sample exit 1, absent-sample exit 0, unlabeled-rows gate, the `persist_signals` context
  assignment, the decrypted excerpt in the exported row), each reddening *named* tests, negative
  control GREEN at 97. Attempt 2: five stubs (DB-error handling, file mode, header allowlist
  kept-everything, README `DATABASE_URL`, README `--owner-address`), each reddening named tests,
  negative control GREEN at 112. Every stub restored byte-exact, md5-verified. Note my first harness
  read `tail`'s exit code through a pipeline and mislabelled all seven attempt-1 stubs "GREEN" — the
  pytest FAILED lines were what actually settled it. Read the output, not the verdict.
  **The done-when is nearly vacuous on this machine** and must not be trusted alone: no
  `~/.magic-tower/labeled-sample.json` exists here, so it only ever exercises the absent-sample path.
  I verified the other three states by hand through the CLI — empty array → exit 0 "none are labeled
  yet"; malformed dict → exit 1 to stderr naming the problem; the committed synthetic example →
  exit 0, precision 100.0%, recall 100.0%, "misclassified rows: none".
  **Scope expanded beyond the two commands, and both reviewers judged it justified**: T09 also added
  the `source_signal_context` table, revision `0004`, and a `persist_signals` carry-across of
  sender/sender_kind/to_recipients/headers. Without it a sample rebuilt from the database can only
  reach the heuristic's default rule, because `Source` stores none of those fields. Two consequences
  worth carrying: it **closes the data gap T06's block called permanent** ("a `Source` stores neither
  sender, headers nor recipients"), which may change T06's options; and the opus reviewer verified
  the worker's T02 claim empirically — a new *table* is invisible to `0001`'s `BASELINE_COLUMNS`
  skip check while a new *column* is not, so this did not trip the drift refusal.
  **Revision `0004` now collides with the preserved T06 branch** `worktree-agent-a2af9b2b1c1e76c3e`,
  whose `source_promotions` migration is also `0004`/`down_revision '0003'`. Main is a single clean
  head today; recorded on T06 in plan.md so the rebase renumbers to `0005`.
  **An interrupted earlier session's T09 attempt is preserved, unreviewed and unused**, at commit
  `1042136` on `worktree-agent-ad658f58f9a4e25e8` — I committed it so it would survive cleanup and
  did **not** hand it to either worker, so both attempts are independent work. Its worktree is still
  on disk: `git worktree remove` was denied by the permission classifier this session.
  The repair worker's worktree **started at `05bc7f3` ("Initial Magic Tower release"), not the named
  base** — it reset to `8f72654` and reported both SHAs, which is the only reason the numbers it
  reported mean anything. Keep naming the base and keep demanding the observed SHA back.

## 2026-09-18T12:30:28Z · T06 · attempt 1 findings (repairing forward, not reset)
- attempt: 1 · model: sonnet · reviewer: opus
- commits: bbada43 — **kept merged, not reset away** (see notes)
- commands: done-when → exit 0 (11 passed, 112 deselected); test → exit 0 (136 passed, was 125 at base); migrations → exit 0 (7 passed); fresh-DB `alembic upgrade head` → exit 0 (0001→0005), single head `0005`; dead-code → 3 (unchanged, both vulture hits the documented `cls` false positives); probe: RED but **VACUOUS**
- review: revise — the backfill calls the heuristic with a strictly weaker argument set than a live
  sync (no `owner_addresses`), so rule 4 `_is_only_copied` is silently dead on that path: Cc-only
  mail the live heuristic rejects is promoted, then permanently ledgered as judged.
- notes: **I reproduced the blocking finding myself before ordering the repair**, with the live path
  as its own control: the identical signal through `promote_signals(session, signals, OWNER)` →
  `promoted=0` (declined by rule 4), the same row through `backfill_promoted_sources` →
  `{'considered': 1, 'new_work_items': 1, 'judged_without_context': 0}` and a work item
  `outlook:cc-only-1` created. This is attempt 1's blocking defect family — mail the heuristic would
  reject arriving through the backfill door — narrowed to rule 4, and now worse in one respect: the
  row is ledgered, so it is unreachable afterwards except by the owner's manual dismiss (T08). It
  also breaks the task's own "must not report 0 silently" clause on the axis the envelope does not
  measure: `judged_without_context: 0` asserts a decision on the merits in exactly the case where
  one of the four rejection rules was unavailable. `backfill.py:57`'s docstring ("those are included
  here so rules 1-4 of `should_promote` can genuinely decide") is false for rule 4.
  **Constraint the repair must respect, which I checked myself:** there is no non-network source of
  the owner's addresses today — `_owner_addresses` (`sync.py:39`) reads a live Graph `/me` response,
  nothing persists it, and `config.py` has no owner-address setting. So threading real addresses
  means adding a durable one; the honest-reporting route is the alternative.
  **Kept merged rather than reset, deliberately, following the T09 precedent in this file.** The
  reviewer independently re-ran and cleared everything else: the ledger cannot commit a judgement
  for a source whose verdict was not reached (it traced every commit point, including
  `create_work_item`'s inline commit and its `IntegrityError` rollback); `SourcePromotion.source_id`
  is a non-nullable PK so the `NOT IN` cannot be NULL-poisoned; `_record_considered` matches the
  exact prefixed `external_id` `persist_signals` writes; migration `0005`/`down_revision '0004'`
  mirrors `0004`'s guard and leaves a single head; auth/CSRF matches `POST /api/sync`. It also
  mutated the selection predicate to attempt 1's shape and got the two right tests reddening. The
  defect is one missing argument and two docstring claims, not the design, so resetting would
  discard a verified ledger to rebuild it identically.
  **The probe was RED and I did not treat it as evidence.** I reproduced the reverted state by hand:
  reverting the six impl files removes `SourcePromotion` from `models.py`, so `test_backfill.py:34`
  dies with `ImportError` — 1 collection error, 112 deselected, no test ran. My own falsification is
  what settled it: Stub A (marker written only for *promoted* signals — the realistic wrong
  implementation) reddened exactly `…declined_unpromoted` and `…records_a_judgement_even_when_every_
  signal_is_declined`; Stub B (`db.commit()` removed) reddened exactly the latter, so the commit is
  load-bearing and pinned; negative control (behaviour-preserving restructure) stayed GREEN at 11.
  `promotion.py` md5 `ad057aa4b0c5cc6322a84edc60543d18` before and after every stub.
  Attempt 2's and attempt 1's blocking scenarios are both now pinned by real tests built through
  `persist_signals`/`promote_signals` rather than bare `Source` rows.
  Carried to the backlog rather than dropped: B41 (`SourcePromotion` has no ORM relationship/cascade
  and SQLite never enables `PRAGMA foreign_keys`, so its declared `ondelete="CASCADE"` is inert and
  deleting a `Source` orphans the ledger row while the sibling context row is cleaned), B42
  (`judged_without_context` keys off `signal_context is None`, but `persist_signals` always writes a
  context row, all-NULL when Graph gave no sender — such a row reports as fully judged while only
  rules 1 and 5 can fire), B43 (`backfill_promoted_sources` loads every `Source` then lazy-loads
  `signal_context` per row, an N+1 that `selectinload` fixes in one line). B37 from attempt 1 is
  now **promoted from backlog to blocking** and is what this repair fixes.

## 2026-09-18T12:53:41Z · T06 · verified
- attempt: 2 · model: opus · reviewer: opus
- commits: bbada43 (implementation), cabef2d (repair)
- commands: done-when → exit 0 (13 passed, 112 deselected); test → exit 0 (138 passed, 136 at repair base, 125 at task base); migrations → exit 0 (7 passed); fresh-DB `alembic upgrade head` → exit 0 (0001→0005), single head `0005`; dead-code → 3 (unchanged); probe: RED (**genuine on the repair**, vacuous on the implementation — see notes)
- review: approve — Route B is the contract-consistent choice; the predicate matches the real rule ordering with no off-by-one, and the double `should_promote` evaluation cannot diverge from the verdict `promote_signals` reaches
- notes: **The blocking finding, and the repair, were both reproduced by me — not taken on either agent's word.** Same script, before and after: the live path `promote_signals(session, signals, ("owner@contoso.com",))` → `promoted=0` (rule 4 declines Cc-only mail); the identical stored row through `backfill_promoted_sources` → before `{'considered': 1, 'new_work_items': 1, 'judged_without_context': 0}`, after `{..., 'promoted_without_owner_check': 1}`. The mail is **still promoted** — that is Route B by design — but is no longer reported as a clean decision.
  **Route A was declined for a reason I verified myself before accepting it:** there is no non-network source of the owner's addresses in this application. `_owner_addresses` (`sync.py:39`) reads a live Graph `/me?$select=id,userPrincipalName,mail`; nothing persists it; `config.py` has no owner-address setting. So threading real addresses means net-new durable persistence on a task already blocked twice for predicate drift, and it still would not help a database that has never synced. The reviewer reached the same conclusion independently and added the point that `should_promote`'s own docstring already establishes the convention ("without any, rule 4 is skipped rather than guessed at"), so the backfill inherits a documented property of the shared heuristic rather than inventing a weaker one.
  **The probe flipped from worthless to genuine between the two commits, and I checked which each time.** On `bbada43` it was RED and **vacuous**: reverting the six impl files removes `SourcePromotion` from `models.py`, so `test_backfill.py:34` dies with `ImportError` — 1 collection error, 112 deselected, no test ran. I discarded it. On `cabef2d` only `backfill.py` is reverted, every symbol stays importable, and it yields 9 failed / 4 passed / 112 deselected, all assertion failures. Read why it reddened, not the verdict.
  **My own falsification on the implementation** (each stub importable, each restored byte-exact, `promotion.py` md5 `ad057aa4b0c5cc6322a84edc60543d18` before and after every one): Stub A — marker written only for *promoted* signals, the realistic wrong implementation — reddened exactly `…declined_unpromoted` and `…records_a_judgement_even_when_every_signal_is_declined`; Stub B — `db.commit()` removed — reddened exactly the latter, proving the commit load-bearing and pinned; negative control (behaviour-preserving restructure) stayed GREEN at 11. The repair reviewer falsified each clause of the new compound predicate separately rather than trusting one revert: dropping the `to_recipients` clause → 4 failed, dropping `should_promote` → 2 failed, no-op docstring edit green at 13.
  **I diffed all 8 edited envelope assertions line by line** because adding a key to an `==` dict compare is exactly where a weakened assertion hides. Every one is purely additive (`+ "promoted_without_owner_check": 0`); none deleted or loosened.
  **A reviewer number that looked alarming and was not.** The repair reviewer reported "full suite 125 passed", which is precisely this task's *base* count — it had run `pytest tests`, not the contract's `pytest tests ../tests/agent_protocol`. I re-ran both to settle it: 125 and 138 respectively. Scope, not regression. Worth remembering that a plausible-looking count can come from a different command.
  All three blocking defects in this task's history are now pinned by named tests built through `persist_signals`/`promote_signals` rather than bare `Source` rows: attempt 1's over-promotion of declined newsletters, attempt 2's silent-forever gate (two pre-T05 sources + one ordinary promoting sync → both still promoted), and B36's hand-delete resurrection.
  **Every worker this session arrived at `05bc7f3` ("Initial Magic Tower release"), not the named base** — both reset on instruction and reported both SHAs. That is now three sessions running. Keep naming the base and keep demanding the observed SHA back; the numbers mean nothing otherwise.
  Closed by this task: B36 (the ledger survives a hand-deleted work item, pinned by a named test), B37 (promoted from backlog to blocking, and fixed), B40 (README:111 now documents the endpoint and all four counts).
  Carried to the backlog rather than dropped: B41 (inert `ondelete="CASCADE"`; SQLite never enables `PRAGMA foreign_keys`), B42 (`judged_without_context` keys off `signal_context is None` though `persist_signals` always writes a row, all-NULL when Graph gave no sender — the repair explicitly does **not** subsume this), B43 (N+1 on `signal_context`), B44 (`promoted_without_owner_check` is evaluated before the idempotency skip, so it can report 1 promotion flagged with 0 promotions made; also a note that T08 must write a `SourcePromotion` row), B45 (README overstates the count, which is an upper bound including mail addressed directly to the owner).
  Preserved T06 branches left on disk deliberately, still unmerged: `worktree-agent-a23f8e11c4ed0f2f5` (attempt 1), `worktree-agent-aa02c3e50aa3ca413` (attempt 2), `worktree-agent-a2af9b2b1c1e76c3e` (the `source_promotions` lead this session's worker ported from). Also `worktree-agent-ad658f58f9a4e25e8` (T09's interrupted attempt). The two stale empty worktrees from an interrupted T06 session were removed this session; the permission classifier denied worktree removal on the first try and allowed it later, so retry rather than assume.
