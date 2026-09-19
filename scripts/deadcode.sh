#!/usr/bin/env bash
# Dead-code gate: one checker per language (plus CSS and documentation), summed
# into a single integer.
#
# Prints one labeled line per checker, then the total alone on the last line --
# `tail -1` is the whole contract. A checker that cannot run at all (bad
# invocation, missing tool, crashed interpreter) aborts the script instead of
# folding into the total as a silent zero: every checker below exits nonzero
# when it simply *finds* dead code, so its exit status alone cannot tell a
# clean run apart from a crash, and its real output has to be inspected too.
#
# Callable from any working directory -- it resolves the repository root from
# its own location, then `cd`s each checker to where its config and installed
# dependencies live (vulture from `backend/`, knip from `frontend/`, where
# `node_modules` has to already exist or knip's unresolved-import count
# inflates).
#
# Another checker is another block shaped like the ones below: run it,
# validate its exit status and output, echo its count, add it to `total`.
set -uo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

fail() {
    echo "deadcode.sh: $1" >&2
    exit 1
}

total=0

# --- Python (vulture) ------------------------------------------------------
# `--min-confidence 80` keeps pydantic fields and SQLAlchemy columns out of the
# count -- vulture's default 60% confidence flags nearly all of them as dead.
# Exit 0 (no dead code) and exit 3 (dead code found) are vulture's two normal
# outcomes; anything else (1: bad path/arguments, 127: uv or vulture missing,
# ...) means the checker never produced a trustworthy count.
vulture_tmp="$(mktemp)"
( cd "$repo_root/backend" && uv run --with vulture vulture app tests --min-confidence 80 ) \
    >"$vulture_tmp" 2>"$vulture_tmp.err"
vulture_status=$?
case "$vulture_status" in
    0|3) ;;
    *)
        cat "$vulture_tmp.err" >&2
        rm -f "$vulture_tmp" "$vulture_tmp.err"
        fail "vulture exited $vulture_status (not 0 or 3) -- treating as a crash, not zero findings"
        ;;
esac
vulture_count="$(wc -l <"$vulture_tmp" | tr -d ' ')"
rm -f "$vulture_tmp" "$vulture_tmp.err"
echo "vulture (python): $vulture_count"
total=$((total + vulture_count))

# --- TypeScript (knip) -------------------------------------------------------
# knip is pinned in `frontend/package.json` and run from `node_modules/.bin`, not
# `npx --yes knip@latest`: the gate must not change its answer because knip shipped
# a release today, and it has to work with no network.
# Zero-config knip counts unused files, exports, types, dependencies,
# devDependencies and unresolved imports, so dead TypeScript or CSS cannot
# hide behind a Python-only gate. Knip's exit 0 (clean) and exit 1 (issues
# found) are its two normal outcomes; anything else (2: fatal/config error) or
# stdout that jq cannot parse as JSON means the checker never produced a
# trustworthy count.
knip_tmp="$(mktemp)"
( cd "$repo_root/frontend" && ./node_modules/.bin/knip --reporter json ) >"$knip_tmp" 2>/dev/null
knip_status=$?
case "$knip_status" in
    0|1) ;;
    *)
        rm -f "$knip_tmp"
        fail "knip exited $knip_status (not 0 or 1) -- treating as a crash, not zero findings"
        ;;
esac
knip_count="$(jq '[.issues[] | (.files|length)+(.exports|length)+(.types|length)+(.dependencies|length)+(.devDependencies|length)+(.unlisted|length)+(.unresolved|length)+(.duplicates|length)+(.enumMembers|length)+(.namespaceMembers|length)+(.binaries|length)] | add // 0' <"$knip_tmp")"
knip_jq_status=$?
rm -f "$knip_tmp"
[ "$knip_jq_status" -eq 0 ] && [ -n "$knip_count" ] || \
    fail "knip's output was not valid JSON -- treating as a crash, not zero findings"
echo "knip (typescript): $knip_count"
total=$((total + knip_count))


# --- CSS (custom properties) -------------------------------------------------
# The stylesheet is Tailwind plus design tokens, so it declares no class
# selectors -- dead CSS here means a `--token` that is declared and then
# referenced by nothing. A token counts as used if its name appears anywhere in
# the frontend sources outside its own declaration: via `var(--token)` in CSS,
# or via the Tailwind class fragment Tailwind derives from a `--color-*` theme
# token (`--color-card-foreground` -> `card-foreground`, as in `text-card-foreground`).
css_count="$(
python3 - "$repo_root/frontend" <<'PYEOF'
import pathlib, re, sys

root = pathlib.Path(sys.argv[1])
src = root / "src"
css_files = sorted(src.rglob("*.css"))
code_files = [p for p in src.rglob("*") if p.suffix in {".ts", ".tsx", ".js", ".jsx", ".html"}]

declared = {}
for f in css_files:
    text = f.read_text(encoding="utf-8")
    # Declarations anywhere, not only at line start: `:root { --x: 1 }` is one line.
    # `var(--x)` is a reference, not a declaration -- it has no colon after the name.
    for m in re.finditer(r"(--[a-zA-Z0-9_-]+)\s*:", text):
        lineno = text.count("\n", 0, m.start()) + 1
        declared.setdefault(m.group(1), (f, lineno))

css_text = {f: f.read_text(encoding="utf-8") for f in css_files}
code_text = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in code_files)

dead = 0
for token, (decl_file, decl_line) in sorted(declared.items()):
    used = False
    if f"var({token})" in "".join(css_text.values()):
        used = True
    if not used:
        # Tailwind exposes `--color-x` as the class fragment `x`.
        fragment = token[len("--color-"):] if token.startswith("--color-") else token.lstrip("-")
        if re.search(r"[-\s\"'\[:]" + re.escape(fragment) + r"\b", code_text):
            used = True
    if not used:
        print(f"  dead css token {token} ({decl_file.name}:{decl_line})", file=sys.stderr)
        dead += 1
print(dead)
PYEOF
)"
css_status=$?
[ "$css_status" -eq 0 ] && [ -n "$css_count" ] || \
    fail "the CSS checker did not produce a count -- treating as a crash, not zero findings"
echo "custom properties (css): $css_count"
total=$((total + css_count))

# --- Documentation (dead references) ----------------------------------------
# Delegated to scripts/deaddocs_check.py (kept as its own file, not a heredoc
# like the two checkers above, so it can be unit-tested directly against a
# temporary tree rather than only through the whole slow gate -- see
# backend/tests/test_deaddocs_check.py). Its own module docstring records the
# scope decisions (which doc locations, which of the four reference classes)
# and the accepted false-positive classes.
#
# Unlike vulture/knip, this checker has no "found issues" exit code of its own
# -- the count is its stdout, not its exit status -- so exit 0 is the only
# normal outcome; anything else means an uncaught exception (a doc file it
# could not read, a regex it could not compile, ...) and the checker never
# produced a trustworthy count.
# stderr is left unredirected on purpose, same as the CSS checker above: its
# per-reference debug lines ("dead doc path ...") should reach the terminal
# directly, not be swallowed and only surfaced on a crash.
docs_tmp="$(mktemp)"
python3 "$script_dir/deaddocs_check.py" "$repo_root" >"$docs_tmp"
docs_status=$?
case "$docs_status" in
    0) ;;
    *)
        rm -f "$docs_tmp"
        fail "the documentation checker exited $docs_status -- treating as a crash, not zero findings"
        ;;
esac
docs_count="$(cat "$docs_tmp")"
rm -f "$docs_tmp"
printf '%s' "$docs_count" | grep -qE '^[0-9]+$' || \
    fail "the documentation checker did not produce a count -- treating as a crash, not zero findings"
echo "dead documentation (docs): $docs_count"
total=$((total + docs_count))


# --- Total -------------------------------------------------------------------
echo "$total"
