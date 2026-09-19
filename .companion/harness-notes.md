# Harness notes — misbehaviour of the loop itself

For the owner to carry to the project-companion repo. Each entry: what happened, evidence, and
what the harness could do instead.

## run 2026-09-17T18-57-48

### H1 — A plan whose headings miss the em dash parses as zero tasks, and the loop silently "succeeds"
`scripts/lib/plan.mjs` requires `^## (T\d+) — (.+)$`. My first `plan.md` used `## T01 Commit the
uv migration` (no em dash), so `parsePlan` returned 0 tasks, `pickNext` returned nothing, the loop
broke out of its first iteration and went straight to final verification with `outcome = "complete"`.
The owner saw `verification-failed` with `_none ran_` under Contract checks and no indication that
the plan had not parsed.
**Evidence:** first `companion build` invocation, run dir `2026-09-17T18-53-36`.
**Suggestion:** if `parsePlan` yields 0 tasks but the file contains `^## T\d+`, fail loudly with the
offending heading. A plan with no parseable tasks should never reach verification as "complete".

### H2 — The verifier executes non-command prose, including command substitution
`VERIFY_LINE` captures everything after `verify:`, and `unquote` only strips backticks when the
*whole* value is one. `- verify: \`cmd\` — both exit 0` therefore reaches `bash -lc` with the
backticks intact, i.e. as command substitution: the command runs, then its stdout is executed as a
command. Observed output: `bash: line 1: .........................: command not found` — pytest's
progress dots being run as a program. Same for `- dead-code: omitted — vulture is not installed`,
where `omitted` was executed.
**Evidence:** `.companion/runs/2026-09-17T18-57-48/` first verification, AC4 and AC5 FAIL.
**Suggestion:** at seal time, reject a `verify:`/`dead-code:` value that contains a backtick but is
not wholly backticked, and warn when a `verify:` line is followed by an indented continuation line
(AC5's `grep` sat on one and was silently ignored). This is a contract-authoring footgun that no
amount of care at authoring time reliably avoids, because the command works when run by hand.

### H3 — Agent worktrees are branched from `main`, not from the current branch HEAD
T01 attempt 1 produced a diff that deleted all of `.companion/`, because its worktree was created
from `main` (`05bc7f3`) while the work sat on `devgod/run_21fb794e4cf5432aac6836c64fdea769`. The
manager caught it and a repair worker reset onto the base first, costing one full task attempt.
**Evidence:** `.companion/progress.md`, T01 notes, attempt 2.
**Suggestion:** branch agent worktrees from the invoking branch's HEAD, or make the worker's first
step an explicit reset onto the base commit the manager names.

### H4 — The vacuity probe is uninformative for test-only and docs-only tasks
The probe's `TEST_PATH` regex treats `conftest.py` and `test_*.py` as test paths and reverts
everything else. A task that touches only test files and documentation has nothing revertible, so
the probe reports VACUOUS (T02) or a meaningless RED with 0 files reverted (T03) — in neither case
did it prove the tests were load-bearing. Real falsification had to be done by hand: stubbing the
fixture body to a bare `yield` produced 2 failures.
**Evidence:** `.companion/progress.md`, T02 and T03 notes.
**Suggestion:** when 0 files are reverted, report `INAPPLICABLE` rather than RED or VACUOUS, and
tell the manager to falsify by hand.

## run 2026-09-18T18-19-10

### H5 — The vacuity probe reverts every impl file at once, so multi-file tasks always probe VACUOUS
Reported by the manager on T06, T09 and T13. The probe reverts all non-test files in the diff
together, so for any task whose test imports a symbol the impl defines, the suite reddens by
`ImportError` rather than by the behaviour under test — a RED that proves nothing. T13's note is
explicit: "reverts all 6 impl files at once, falsified per clause by hand instead."
**Suggestion:** revert one impl file at a time and report per-file results, or report
`INAPPLICABLE` when the revert causes a collection/import error rather than a test failure.

### H6 — `companion build` reports `complete` when every remaining task is blocked
Twice this run the loop hit a state where all runnable tasks were done and the rest were blocked
behind one `blocked(...)`, then ran final verification and exited `verification-failed`. The
outcome is technically right but reads as "the build failed" rather than "the build is waiting on
a decision", which is the actual state.
**Suggestion:** distinguish `blocked` from `verification-failed` in the final line, and name the
blocking task id.

### H7 — A filtered test command is accepted as a gate even when it matches nothing
`npm run test -- -t <pattern>` exits 0 when no test matches, so a `done-when` of that shape can be
satisfied with zero tests written. Confirmed by hand: a bogus pattern exits 0. pytest's `-k` exits
5 in the same situation, so the hazard is runner-specific and easy to miss.
**Suggestion:** at seal time, reject a `done-when`/`verify:` that filters by test name without
asserting a count, or require `--passWithNoTests=false` equivalents per runner.

## run 2026-09-19 (cleanup)

### H8 — Agent worktrees and their branches are never reaped
After this contract the repository held **15 agent worktrees and 21 `worktree-agent-*` branches**,
the oldest from days earlier. Nine held uncommitted edits from abandoned attempts. The loop creates
a worktree per task attempt and never removes it, so the count grows without bound; `.claude/` was
gitignored earlier in this run specifically to stop them dirtying `git status`, which hid the
growth rather than fixing it.
**Suggestion:** remove the worktree and delete its branch when a task reaches `verified`, or when
its attempt is abandoned. If uncommitted work must be preserved, write it as a patch outside the
repository and say where.

### H9 — Workers write scratch files to /tmp, not the session scratchpad
224 files matching this project's task names (`ac*.log`, `t0*.db`, `ciprobe/`, `workboard-tests*`,
`conftest.keep`, …) were left in `/tmp` by worker sessions. They are invisible to `git status`, so
nothing in the loop ever notices them.
**Suggestion:** give workers a per-run scratch directory and clean it when the run ends.

### H10 — Nothing stops processes a session starts
A `vite --port 5173` dev server started during `/companion:present` was still running roughly six
hours later, along with a docker compose stack. The loop has no notion of process ownership.
**Suggestion:** track processes started during a run and stop them at run end, or report them.

