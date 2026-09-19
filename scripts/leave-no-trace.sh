#!/usr/bin/env bash
# Leave-no-trace gate: counts artefacts a run leaves behind that nobody is
# still using -- stray worktrees, orphan agent branches, forgotten task-scoped
# /tmp files, and repo-pointing processes still alive.
#
# Prints one labeled line per category, then the total alone on the last line
# -- `tail -1` is the whole contract, same shape as `scripts/deadcode.sh`.
# A category that cannot be measured at all (git missing, /proc unreadable)
# aborts the script via `fail()` instead of folding into the total as a
# silent zero, for the same reason `deadcode.sh` validates each checker's
# exit status: a gate that prints "0 left behind" when a category never ran
# is worse than no gate, because it looks green.
#
# --- Decision: the worktree and branch running THIS check are not "left
# behind" -----------------------------------------------------------------
# This script resolves its own repository root the same way deadcode.sh does
# (from its own file location), and that root is itself always an entry in
# `git worktree list` whenever this script runs from inside an agent
# worktree -- which it does on every ordinary run, including the manager's
# own final check before merge if that check happens to run from a worktree
# instead of the main tree. Without an exclusion the gate would be trivially
# red on every single invocation. The fix: a worktree only counts as stray if
# it is neither the main worktree (`git worktree list` always lists the main
# tree first -- a stable implementation detail, not incidental ordering) nor
# the one this script is running from. Symmetrically, a `worktree-agent-*`
# branch only counts as an orphan if it is not checked out by ANY worktree
# `git worktree list` currently reports -- a branch checked out somewhere is
# an active session, not something "left behind"; a branch with no worktree
# pointing at it is exactly what the retro called an orphan branch.
#
# --- Decision: /tmp is scoped to this project's own task/AC naming, not all
# of /tmp --------------------------------------------------------------------
# The machine's /tmp has on the order of a thousand entries unrelated to this
# project, so "every /tmp entry" is not a usable signal. This project's own
# sessions name their scratch files after the task or acceptance-criterion ID
# they belong to -- `/tmp/ac13.json`, `/tmp/t11.json`, `/tmp/ac4-alembic.db`,
# `/tmp/t03-clone-test`, all visible in `.companion/runs/*/verification.md`
# history -- so the category matches top-level `/tmp` entry basenames
# case-insensitively against `ac<digits>` or `t<digits>`, and the ID has to
# END there: at a `.`, `-`, `_`, or the end of the name. The terminator is
# not decoration. Several unrelated tools name their /tmp entries with
# random 21-character nanoids, and about one in two hundred of those opens
# with `t` or `ac` followed by a digit -- `/tmp/t2zBWPxqUQ5ntZbhoh4Ai` is a
# real one on this machine. On a bare prefix match the gate went red for an
# artefact this project never created and cannot clean up, which trains
# everyone to ignore it. Matching is non-recursive (top-level names only) so
# the category stays cheap and does not have to reason about unrelated
# directory trees underneath /tmp.
#
# --- Decision: exactly two basenames are exempt ------------------------------
# A file a verify command writes and never cleans up is normally exactly the
# trace this gate exists to catch. The two exceptions are named by a SEALED
# contract that this script cannot edit to clean up after itself, and both
# are rewritten every time that contract is verified -- so counting them
# would make this gate red by construction, including in its own AC4 gate
# `bash scripts/leave-no-trace.sh && ...`, whose first clause would then
# never pass. They are exempted by exact basename, never by class: a stale
# report like `/tmp/t2.json`, left by an earlier contract's task and
# mandated by nothing, still counts. Exempting "*.json" or "anything a
# verify command might write" would make the gate worthless.
#
# --- Seam: LEAVE_NO_TRACE_TMP_DIR --------------------------------------------
# The directory this category scans, defaulting to /tmp. It exists so the
# naming rules above can be falsified against a private directory: proving
# `ac13.json` is exempt needs a file by that exact name, and the real
# /tmp already holds one that AC13's verify command wrote and that no test
# may clobber or delete. The rise-and-fall test passes no override, so the
# default /tmp path stays exercised.
set -uo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

fail() {
    echo "leave-no-trace.sh: $1" >&2
    exit 1
}

total=0

# --- git worktree/branch state -----------------------------------------
# Fetched once and reused by both the worktree and branch categories below,
# same data, two different questions asked of it.
worktree_raw="$(git -C "$repo_root" worktree list --porcelain)"
worktree_status=$?
[ "$worktree_status" -eq 0 ] || \
    fail "git worktree list exited $worktree_status -- treating as a crash, not zero findings"
[ -n "$worktree_raw" ] || \
    fail "git worktree list produced no output at all -- treating as a crash, not zero findings"

# --- Stray worktrees -----------------------------------------------------
stray_worktrees=0
first=1
while IFS= read -r line; do
    case "$line" in
        worktree\ *)
            wt_path="${line#worktree }"
            if [ "$first" -eq 1 ]; then
                first=0
                continue
            fi
            [ "$wt_path" = "$repo_root" ] && continue
            stray_worktrees=$((stray_worktrees + 1))
            ;;
    esac
done <<<"$worktree_raw"
echo "stray worktrees: $stray_worktrees"
total=$((total + stray_worktrees))

# --- Orphan worktree-agent-* branches --------------------------------------
branch_raw="$(git -C "$repo_root" branch --list --format='%(refname:short)' 'worktree-agent-*')"
branch_status=$?
[ "$branch_status" -eq 0 ] || \
    fail "git branch --list exited $branch_status -- treating as a crash, not zero findings"

checked_out_branches="$(printf '%s\n' "$worktree_raw" | awk '/^branch /{sub("refs/heads/","",$2); print $2}')"

is_checked_out() {
    local name="$1" line
    while IFS= read -r line; do
        [ "$line" = "$name" ] && return 0
    done <<<"$checked_out_branches"
    return 1
}

orphan_branches=0
while IFS= read -r br; do
    [ -z "$br" ] && continue
    is_checked_out "$br" && continue
    orphan_branches=$((orphan_branches + 1))
done <<<"$branch_raw"
echo "orphan worktree-agent branches: $orphan_branches"
total=$((total + orphan_branches))

# --- Stray /tmp task files --------------------------------------------------
tmp_dir="${LEAVE_NO_TRACE_TMP_DIR:-/tmp}"
tmp_raw="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -printf '%f\n')"
tmp_status=$?
[ "$tmp_status" -eq 0 ] || \
    fail "listing $tmp_dir exited $tmp_status -- treating as a crash, not zero findings"

stray_tmp=0
while IFS= read -r name; do
    [ -z "$name" ] && continue
    # `t<digits>` / `ac<digits>` terminated by `.`, `-`, `_` or end of name.
    [[ "$name" =~ ^([Aa][Cc]|[Tt])[0-9]+([._-]|$) ]] || continue
    case "$name" in
        # AC13's verify command writes /tmp/ac13.json on every run.
        ac13.json) continue ;;
        # Plan task T11's done-when writes /tmp/t11.json the same way.
        t11.json) continue ;;
    esac
    stray_tmp=$((stray_tmp + 1))
done <<<"$tmp_raw"
echo "stray /tmp task files: $stray_tmp"
total=$((total + stray_tmp))

# --- Repo-pointing processes -------------------------------------------------
# "Points inside this repository" is checked against the MAIN worktree's
# absolute path, not this script's own (possibly linked) worktree: every
# linked worktree this project creates lives underneath the main tree
# (`<main>/.claude/worktrees/...`), so matching the main tree's path alone
# still catches a leaked dev server or container regardless of which
# worktree started it.
#
# The process running this script itself, and every one of its ancestors up
# to PID 1 (the shell that invoked it, `uv run pytest` when a test in
# `backend/tests/` runs this script as a subprocess, ...), is excluded --
# those are legitimately alive right now and are not "left behind". Anything
# else whose command line mentions the main tree's path is counted, matching
# the retro's example of a vite dev server left running for hours.
main_worktree="$(printf '%s\n' "$worktree_raw" | awk '/^worktree /{print substr($0, 10); exit}')"
[ -n "$main_worktree" ] || \
    fail "could not determine the main worktree path -- treating as a crash, not zero findings"

ppid_of() {
    local stat
    stat="$(cat "/proc/$1/stat" 2>/dev/null)" || return 1
    stat="${stat##*) }"
    set -- $stat
    printf '%s\n' "$2"
}

self_pid=$$
ancestor_pids=" $self_pid "
walk_pid="$self_pid"
while :; do
    parent="$(ppid_of "$walk_pid")"
    [ -z "$parent" ] && break
    [ "$parent" = "0" ] && break
    ancestor_pids="$ancestor_pids$parent "
    [ "$parent" = "1" ] && break
    walk_pid="$parent"
done

repo_processes=0
proc_scan_ran=0
for cmdline_file in /proc/[0-9]*/cmdline; do
    [ -e "$cmdline_file" ] || continue
    proc_scan_ran=1
    pid="$(basename "$(dirname "$cmdline_file")")"
    case "$ancestor_pids" in
        *" $pid "*) continue ;;
    esac
    cmd="$(tr '\0' ' ' <"$cmdline_file" 2>/dev/null)"
    [ -z "$cmd" ] && continue
    case "$cmd" in
        *"$main_worktree"*) repo_processes=$((repo_processes + 1)) ;;
    esac
done
[ "$proc_scan_ran" -eq 1 ] || \
    fail "no /proc/<pid>/cmdline entries were readable -- treating as a crash, not zero findings"
echo "repo-pointing processes: $repo_processes"
total=$((total + repo_processes))

# --- Total -------------------------------------------------------------------
# Unlike deadcode.sh (which only ever reports a count), this gate's contract
# is to *fail* when anything was left behind, so the total line is followed
# by a nonzero exit whenever it is not zero.
echo "$total"
[ "$total" -eq 0 ] || exit 1
