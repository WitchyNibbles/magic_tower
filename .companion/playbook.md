# Playbook — questions to ask early, learned from past runs

Each entry is a question a retro said was asked too late. Carry them into `/companion:explore`
and `/companion:contract`.

## From run 2026-09-17T18-57-48 (backend suite green)

- **Have I run each `verify:` command through the verifier's own parser, not just by hand?**
  Contract verify lines are executed verbatim by `bash -lc`. The parser only strips backticks when
  the *entire* value is one, so `` verify: `cmd` — both exit 0 `` becomes command substitution:
  the command runs, then its stdout is executed as a command. A continuation line under a
  `verify:` is never read at all. Same trap for `dead-code:` — prose there is run as a command, so
  omit the key rather than explaining why it is absent. Check with:
  `node -e "import('…/companion-verify.mjs').then(m=>console.log(m.verifyCommands(contract)))"`.
  Running the command by hand in a terminal does NOT test this; only the parser's form does.

- **Is there a `dead-code:` command, and what is its honest baseline?**
  "No tool installed" is not an acceptable reason to skip the gate. Measure it, even if the number
  turns out to be noise. For this repo: `cd backend && uv run --with vulture vulture app tests
  --min-confidence 80 | wc -l` → baseline **2**, both `cls` in `@classmethod` pydantic validators,
  i.e. false positives. At the default 60% confidence it reports 80 findings, nearly all pydantic
  fields / `model_config` / SQLAlchemy columns / pytest fixtures — useless as a gate.

- **Can any acceptance criterion only be proved by pushing? Then push.**
  AC8 (CI goes green) was written as half-manual and left unproven at Gate 2. A push settles it in
  ~2 minutes. Leaving a criterion untested when a remote exists is a choice, not a constraint.

- **Where does the harness branch agent worktrees from?**
  From `main`, not from the current branch HEAD. A worker that does not reset onto the base first
  will produce a diff that deletes everything added on the branch since `main` — it cost T01 its
  first attempt by deleting all of `.companion/`.

- **Does the vacuity probe have anything revertible for this task?**
  The probe classifies `conftest.py` and `test_*.py` as test paths. A task that touches only test
  files and docs has no impl file to revert, so the probe reports VACUOUS or a meaningless RED and
  proves nothing. For those tasks, falsify by hand instead (stub the fixture body, confirm red).

- **Where do out-of-scope findings go?**
  Into `.companion/backlog.md`, in the same session they are found. A non-goal in the contract is
  a scheduling decision, not a decision to forget.
