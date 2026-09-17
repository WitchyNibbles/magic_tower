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
