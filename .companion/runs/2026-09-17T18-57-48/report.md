# Report — backend suite green, for real and for everyone · run 2026-09-17T18-57-48

## Result
The backend suite now passes from a fresh clone, which is the thing that was actually broken —
it always passed in your working tree. 26 tests green in 2.3s. There was no AnyIO portal hang:
the failure was an import-order bug, and the fix for it was already sitting untracked in your
tree, which is why it looked green to you and red to everyone else.

## Verified live
Every command below was run by me in this session just now, not copied from progress.md.

| Criterion | Command | Result |
|---|---|---|
| AC1 | fresh clone → `uv sync && uv run pytest tests ../tests/agent_protocol` | pass — 26 passed in 2.32s |
| AC2 | `git ls-files --error-unmatch` pyproject/uv.lock/conftest | pass |
| AC3 | README has the green command, no `hang`/`AnyIO portal` | pass |
| AC4 | two suites in parallel, both exits checked | pass — 13 passed each |
| AC4 | conftest no longer pins `/tmp/workboard-tests.db` | pass |
| AC5 | suite with `--timeout=30` + `^timeout` in pyproject | pass — 26 passed in 1.97s |
| AC6 | `pytest -k session_store_is_isolated` | pass — 2 passed, 11 deselected |
| AC7 | `docker compose build` from a fresh clone | pass — both images built |
| AC8 | CI workflow parses and contains the test + docker commands | pass |
| AC9 | `uv sync && ./.venv/bin/magic-tower-api --help` | pass |
| AC10 | tree clean after a test cycle | pass |

## Running
Live now on **http://127.0.0.1:8011** (started with the contract's `run:` command, port changed
from the default to avoid colliding with anything you have on 8000):

    cd backend && DATABASE_URL=sqlite:///./workboard.db LOCAL_API_TOKEN=present-smoke-token \
      uv run uvicorn app.main:app --port 8011

- `GET /api/health` → 200, with `cache-control: no-store`, `x-content-type-options: nosniff`,
  `x-frame-options: DENY`, `referrer-policy: no-referrer`, `cross-origin-resource-policy: same-origin`
- `GET /api/work-items` with no token → **401**; with the bearer token → **200 `[]`**

Logs: `/tmp/claude-1000/-home-eimi-projects-magic-tower/749d753a-7f2c-47c1-b828-95fb51326bb9/scratchpad/uvicorn.log`.
Stop it with `pkill -f "uvicorn app.main:app"`.

## What was built
| Task | Model(s) | Review | Commit(s) |
|---|---|---|---|
| T01 — uv migration tracked, `[build-system]`, `.gitignore` | opus (attempt 2) | fable — approve | `418eba1` |
| T02 — conftest tracked, README hang claim removed | sonnet | opus — approve, 2 advisories | `a0d7019` |
| T03 — per-process database | opus (attempt 2) | fable — approve | `3e36fdd` |
| T04 — `pytest-timeout`, `timeout_method = "thread"` | opus (attempt 2) | fable — approve, 2 advisories | `79bf111` |
| T05 — session store cleared between tests | sonnet | opus — approve, 2 advisories | `23d6c70` |
| T06 — CI workflow (tests + docker build) | sonnet | opus — approve, 3 advisories | `56a6824` |

Three tasks needed a second attempt. T01 attempt 1 was rejected because the harness creates agent
worktrees from `main` (`05bc7f3`), not from branch HEAD, so its diff deleted all of `.companion/`.
T03 attempt 1 was rejected for putting the regression guard only in the `done-when` command
instead of in a test. Plus one contract repair by me, `508b72d` — see residuals.

## Blocked
| Task | Reason |
|---|---|
| — | none; T01–T06 all verified |

## Not verified (residuals)
- **AC8 is half manual.** The workflow file parses and contains the right commands, but nothing
  here can execute GitHub Actions — no runner, no actionlint. It goes green on first push or it
  does not. This is the largest unverified thing in the run.
- **Dead code was never measured.** The contract carries no `dead-code:` command because vulture
  is not installed, so there is no baseline and no delta. Verification says so itself.
- **The vacuity probe proved nothing for T02 and T03.** T02: the probe's `TEST_PATH` regex treats
  `conftest.py` and `test_*.py` as test paths, and T02 touched only test files and docs, so it had
  nothing revertible — reverting a README cannot redden a suite. The manager confirmed real RED by
  hand at base (fresh clone → 13 passed, 5 errors, `unable to open database file '/data/workboard.db'`)
  and the reviewer re-probed by stubbing the fixture to a bare `yield` → 2 failures. T03: RED but
  uninformative, 0 files reverted.
- **My own contract was wrong on the first run**, and the first verification failed because of it,
  not because of the work. AC4 and AC5 had prose trailing a backticked command; the verifier only
  strips backticks when the whole value is one, so bash received them as command substitution and
  executed pytest's dotted output as a command. The `dead-code: omitted — …` prose was run as a
  command too. Fixed in `508b72d` and re-sealed as `cc3579b8`.
- **`@app.on_event("startup")` is still deprecated** at `backend/app/main.py:46`. Out of scope by
  the contract's own non-goals, but it blocks any fastapi/starlette upgrade.
- Run transcripts (`*.jsonl`) and `.companion/runs/` are excluded from git per your choice, so the
  audit trail for this run lives only on this machine.

## Transcript scan
27 hits, all false positives. Every one is a worker *grepping for* hack words, or cleaning its own
`/tmp` scratch directory — none is a suppression added to your code. I checked the diffs. Verbatim
from verification.md:

    - `rm -rf .venv magic_tower_api.egg-info workboard.db __pycache__ tests` in T01-1-0.jsonl: …-tower/.claude/worktrees/agent-a3ddd7d6d50d3e326/backend && rm -rf .venv magic_tower_api.egg-info workboard.db __pycache…
    - `xfail` in T01-1-0.jsonl: …ff aa2a5e3..HEAD -- . ':!backend/uv.lock' | grep -nE \"skip|xfail|noqa|ts-ignore|no-verify|print\\(|TODO|FIXME\" || echo…
    - `noqa` in T01-1-0.jsonl: …a5e3..HEAD -- . ':!backend/uv.lock' | grep -nE \"skip|xfail|noqa|ts-ignore|no-verify|print\\(|TODO|FIXME\" || echo none"…
    - `xfail` in T01-1-0.jsonl: …anion/`, README, or `backend/tests/` paths in diff; no skip/xfail/noqa/print/TODO additions; no security-relevant code t…
    - `noqa` in T01-1-0.jsonl: …`, README, or `backend/tests/` paths in diff; no skip/xfail/noqa/print/TODO additions; no security-relevant code touched…
    - `rm -f backend/tests` in T02-1-0.jsonl: …/tests/test_security.py backend/tests/test_work_items.py && rm -f backend/tests/conftest.py && echo \"--- pre-merge stat…
    - `rm -rf /tmp/t03-clone-test/clone && cd /home/eimi/projects/magic-tower/.claude/worktrees/agent-ab1f51c4b6f757314 && git clone -q . /tmp/t03-clone-test` in T03-1-0.jsonl: …:"Bash","input":{"command":"mkdir -p /tmp/t03-clone-test && rm -rf /tmp/t03-clone-test/clone && cd /home/eimi/projects/m…
    - `rm -rf /tmp/t03-clone-test` in T03-1-0.jsonl: …01HYbe5NQC7vBHa4J4M6Uw3a","name":"Bash","input":{"command":"rm -rf /tmp/t03-clone-test && cd /home/eimi/projects/magic-t…
    - `rm -rf /tmp/workboard-tests-fixed /tmp/conftest.keep && git -C /home/eimi/projects/magic-tower/.claude/worktrees/agent-a7c7bb6c182fa67ef diff --stat","description":"Falsify test` in T03-1-0.jsonl: …IPESTATUS[0]}\"; cp /tmp/conftest.keep tests/conftest.py && rm -rf /tmp/workboard-tests-fixed /tmp/conftest.keep && git …
    - `rm -rf /tmp/workboard-tests-fixed /tmp/conftest.keep && uv run pytest tests/test_database_isolation.py -q -p no:warnings 2>&1 | tail -3; echo \"RESTORED EXIT=${PIPESTATUS[0]}\"","description":"Restore conftest and confirm test` in T03-1-0.jsonl: …a67ef/backend && cp /tmp/conftest.keep tests/conftest.py && rm -rf /tmp/workboard-tests-fixed /tmp/conftest.keep && uv r…
    - `rm -rf \"$d\"","description":"AC1 fresh clone install and test` in T03-1-0.jsonl: …arnings 2>&1 | tail -3; echo \"AC1 EXIT=${PIPESTATUS[0]}\"; rm -rf \"$d\"","description":"AC1 fresh clone install and te…
    - `rm -rf /tmp/ac1clone; cd /home/eimi/projects/magic-tower/.claude/worktrees/agent-a7c7bb6c182fa67ef/backend && uv run pytest tests -q >/dev/null 2>&1; echo \"suite=$?\"; cd /home/eimi/projects/magic-tower/.claude/worktrees/agent-a7c7bb6c182fa67ef && git status --porcelain; test -z \"$(git status --porcelain)\"; echo \"AC10 EXIT=$?\"","description":"AC10 clean worktree after test` in T03-1-0.jsonl: …01Npru2HEQABeQ98mif4J2jp","name":"Bash","input":{"command":"rm -rf /tmp/ac1clone; cd /home/eimi/projects/magic-tower/.cl…
    - `rm -rf /tmp/ac1clone; cd /home/eimi/projects/magic-tower/.claude/worktrees/agent-a7c7bb6c182fa67ef/backend && uv run pytest tests` in T03-1-0.jsonl: …01Gx9tJWero7VqNGwaYXkGh1","name":"Bash","input":{"command":"rm -rf /tmp/ac1clone; cd /home/eimi/projects/magic-tower/.cl…
    - `rm -rf \"$d\"; echo \"--- stale temp dirs now: $(ls -d /tmp/workboard-tests` in T03-1-0.jsonl: …?\"; tail -1 /tmp/ac1b.log; git -C \"$d\" log --oneline -1; rm -rf \"$d\"; echo \"--- stale temp dirs now: $(ls -d /tmp/…
    - `rm tests` in T04-1-0.jsonl: …failed|passed\" | head -5; echo \"EXIT: ${PIPESTATUS[0]}\"; rm tests/test_zz_tmp_hang.py","description":"Prove real hang…
    - `rm tests` in T04-1-0.jsonl: …failed|passed\" | head -5; echo \"EXIT: ${PIPESTATUS[0]}\"; rm tests/test_zz_tmp_hang.py","description":"Prove real hang…
    - `rm -rf /tmp/ac1-clone-t04 /tmp/pp.bak; cd /home/eimi/projects/magic-tower/.claude/worktrees/agent-a7f22b377bc6bcef4/backend && uv run pytest tests -q > /dev/null 2>&1; echo \"TESTS: $?\"; cd /home/eimi/projects/magic-tower/.claude/worktrees/agent-a7f22b377bc6bcef4 && test -z \"$(git status --porcelain)\"; echo \"AC10 EXIT: $?\"","description":"AC10 clean status after test` in T04-1-0.jsonl: …01UtwokBjGekeY98Vwq6rAky","name":"Bash","input":{"command":"rm -rf /tmp/ac1-clone-t04 /tmp/pp.bak; cd /home/eimi/project…
    - `rm -rf /tmp/ac1-clone-t04 /tmp/pp.bak; cd /home/eimi/projects/magic-tower/.claude/worktrees/agent-a7f22b377bc6bcef4/backend && uv run pytest tests -q > /dev/null 2>&1; echo \"TESTS: $?\"","description":"Run backend tests` in T04-1-0.jsonl: …014rmFfLnqVM5thBMHABq2vm","name":"Bash","input":{"command":"rm -rf /tmp/ac1-clone-t04 /tmp/pp.bak; cd /home/eimi/project…
    - `xfail` in T04-1-0.jsonl: …ck-words---; git diff 6670021..HEAD | grep -nE '^\\+.*(skip|xfail|noqa|ignore|no-verify|print\\()' || echo none","descri…
    - `noqa` in T04-1-0.jsonl: …ds---; git diff 6670021..HEAD | grep -nE '^\\+.*(skip|xfail|noqa|ignore|no-verify|print\\()' || echo none","description"…
    - `xfail` in T05-1-0.jsonl: … /tmp/mt-judge; git diff a2e52a7..23d6c70 | grep -nE \"skip|xfail|noqa|ts-ignore|print\\(|TODO|FIXME|no-verify\" || echo…
    - `noqa` in T05-1-0.jsonl: …mt-judge; git diff a2e52a7..23d6c70 | grep -nE \"skip|xfail|noqa|ts-ignore|print\\(|TODO|FIXME|no-verify\" || echo \"no …
    - `xfail` in T05-1-0.jsonl: … no dead code, no debug output, no hack words (grepped skip/xfail/noqa/print/TODO/no-verify — none), no formatting churn…
    - `noqa` in T05-1-0.jsonl: …ad code, no debug output, no hack words (grepped skip/xfail/noqa/print/TODO/no-verify — none), no formatting churn; diff…
    - `rm -rf /tmp/ciprobe/$name\n  mkdir -p /tmp/ciprobe/$name/tests/agent_protocol /tmp/ciprobe/$name/.github/workflows\n  cp tests/agent_protocol/test_ci_workflow.py /tmp/ciprobe/$name/tests/agent_protocol/\n  \"$@\" > /tmp/ciprobe/$name/.github/workflows/ci.yml\n  echo \"=== $name ===\"\n  /home/eimi/projects/magic-tower/backend/.venv/bin/python -m pytest -p no:cacheprovider -q /tmp/ciprobe/$name/tests/agent_protocol/test_ci_workflow.py 2>&1 | tail -3\n}\nprobe baseline cat .github/workflows/ci.yml\nprobe drop_agent_protocol sed 's| \\.\\./tests/agent_protocol||' .github/workflows/ci.yml\nprobe drop_pull_request sed '/pull_request:/d' .github/workflows/ci.yml\nprobe drop_docker sed 's|docker compose build|echo nope|' .github/workflows/ci.yml\nprobe wrong_python sed 's|\"3.12\"|\"3.11\"|' .github/workflows/ci.yml\nprobe drop_workdir_all sed '/working-directory: backend/d' .github/workflows/ci.yml\nprobe drop_setup_uv sed '/astral-sh\\/setup-uv@v5/d' .github/workflows/ci.yml","description":"Mutation-test` in T06-1-0.jsonl: …& mkdir -p /tmp/ciprobe\nprobe() {\n  name=\"$1\"; shift\n  rm -rf /tmp/ciprobe/$name\n  mkdir -p /tmp/ciprobe/$name/tes…
    - `xfail` in T06-1-0.jsonl: …nput":{"command":"git diff 9069994..HEAD | grep -nEi \"skip|xfail|noqa|ts-ignore|no-verify|print\\(|TODO|FIXME\" || echo…
    - `noqa` in T06-1-0.jsonl: …{"command":"git diff 9069994..HEAD | grep -nEi \"skip|xfail|noqa|ts-ignore|no-verify|print\\(|TODO|FIXME\" || echo \"no …

## Next
Give feedback on this run, then `/companion:retro`.
