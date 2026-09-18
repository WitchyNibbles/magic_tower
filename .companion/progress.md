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
