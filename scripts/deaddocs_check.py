#!/usr/bin/env python3
"""Dead-documentation checker for ``scripts/deadcode.sh``'s dead-code gate.

Flags five kinds of documentation reference that name something this repo does
not actually have: a file path (backtick-quoted or a markdown-link target), a
`METHOD /api/...` endpoint, a bare `ENV_VAR_NAME`, a `-m module.path` command,
and a retired *capability* -- a connector the code no longer has.

Scope decisions, made explicit here because each cost a false positive to find:

* ``.companion/harness-notes.md`` is excluded entirely. Its own header says it
  is "for the owner to carry to the project-companion repo" -- a different
  codebase -- so every path or identifier in it is a claim about code this
  checker cannot see.
* Endpoint, env-var, command and capability checks are further scoped to
  ``README.md`` and ``docs/`` only, and no narrower: those two locations are
  this repo's user-facing description of what the app does *today* -- the
  audience a stale capability claim actually misleads -- so every file there
  is in scope, not a selected subset. The rest of ``.companion/*.md`` is a
  session-by-session
  historical log (backlog, progress, plan, contract, explore) that narrates
  other systems' APIs (a Freshservice/Jira connector sketch in ``explore.md``)
  and even the harness's own internal names inline in prose (``backlog.md``'s
  `TEST_PATH` entry names the *manager's* regex, not this repo's) --
  indistinguishable from a real dead reference by a checker this simple. The
  log also has to be able to record *that* a connector was removed, which the
  capability check would otherwise count as dead documentation of its own
  history. File paths are still checked across all of ``.companion/*.md``
  (minus harness-notes.md): a broken path is a narrower, more objective claim
  than an endpoint or a bare identifier, so it stays in scope there.
* Absolute paths (``/api/...``, ``/data``, ``/me``) are someone else's
  namespace (this app's own HTTP API, a container mount, Microsoft Graph), not
  a filesystem claim, and are excluded from the path check.
* A path is checked against the repo root *and* each subproject root
  (``backend/``, ``frontend/``), since docs switch base directory mid-file
  after a `cd backend`.
* A path that resolves nowhere but matches a ``.gitignore`` pattern (a build
  artifact, ``node_modules``, a user-created ``.env``) is treated as
  expected-absent, not dead.
* An `ENV_VAR_NAME` is checked against every identifier spelled anywhere in
  the app, CLI scripts and tests, case-folded to upper -- deliberately broad,
  so a snake_case Settings field like `token_store_path` counts as backing
  `TOKEN_STORE_PATH`. The goal is to catch a name invented in docs that
  appears *nowhere* in the code at all (the way `teams_message` no longer
  does), not to police naming style.
* An endpoint reference is only judged "ours to know about" if its first path
  segment after `/api/` matches a segment some real FastAPI router uses --
  otherwise it names someone else's API and is left alone rather than guessed
  at.
* The retired-capability vocabulary is *derived*, never hardcoded, so cutting
  the next connector needs no edit here: ``SourceKind`` in
  ``backend/app/models.py`` is what the code supports now, and
  ``backend/alembic/versions/*.py`` is every kind the schema has ever spelled
  (an initial ``sa.Enum(..., name="sourcekind")`` listing, plus the
  ``..._KIND = "..."`` constant a removal migration deletes rows by). A kind
  the migrations know and the enum does not is retired, and the first segment
  of a kind names its connector (``teams_message`` -> ``teams``). A connector
  name doubles as an ordinary English word, so the match is made on casing,
  not on a word list: any spelling *except* the all-lowercase one counts as a
  proper-noun claim about the connector ("Teams", "OneDrive", "TEAMS"), while
  the bare lowercase word is left to prose ("small teams of agents"). The unit
  is the doc line, the way the backlog counts these, so one wordy sentence
  does not outweigh three separately wrong ones.

Known false positives (accepted, same class as vulture's pydantic-field noise
documented in the contract): a doc line that *asserts an absence*
(``.companion/progress.md``'s "there is no `frontend/.gitignore`") reads as a
positive existence claim to this checker, which does no negation detection;
and a bare identifier that names the *manager's own harness*, not this repo,
inside an otherwise in-scope file (``.companion/backlog.md``'s `TEST_PATH`)
cannot be told apart from a real dead reference without knowing which repo
each backlog entry's code is even in.

Known gaps (dead references this deliberately does not reach): the doc scope is
the three locations the task names -- ``README.md``, ``docs/`` and
``.companion/*.md`` -- so stale capability claims in ``skills/*/SKILL.md`` and
``.codex-plugin/plugin.json`` are outside it. A delegated Graph scope the docs
tell the reader to register but ``GRAPH_SCOPES`` in
``backend/app/services/oauth.py`` does not request (``Chat.Read``, today) is a
sixth class this does not implement; the lines carrying it are caught anyway
wherever they also name the connector, but not where they name only the scope.
A path written relative to its referring file's parent (`../docs/x.md`) is
discarded rather than resolved. Every path here is resolved against a *fixed*
set of bases -- the repo root and each subproject root -- precisely because
docs switch base directory mid-file after a `cd backend`, so there is no
referring directory to walk `..` up from. Stripping the `../` and resolving
the remainder against those bases (what the pre-T21 ``lstrip("./")`` did by
accident, which is why such a line used to be flagged) is only right when the
referring doc happens to sit exactly one level down; from ``README.md`` at the
root it points outside the repo entirely. Guessing which is meant would cost
more than the class is worth: the only such link in this repo today
(``docs/second-pc.md:56``, ``../README.md#develop-the-api-with-uv``) points at a
live file, so neither policy would change the count.

A bare (slash-less) token starting with a dot -- `.env`, but also `.dark`, a
CSS class, or `.toLowerCase()`, a method call -- is never reported: its
shape cannot tell a real dotfile reference apart from prose that merely
starts with a dot, and this repo's own docs (`.companion/*.md` especially,
full of quoted CSS/JS/regex fragments) currently need the second case not to
be a false positive far more than they need the first case caught. No branch
is spent on this: such a token *is* its own first path segment, so it either
names a real top-level entry -- which therefore exists -- or falls out at the
"not a claim about this repo" top-level filter.
"""
import ast
import re
import subprocess
import sys
import pathlib


def _candidates(text, backtick, md_link):
    for m in backtick.finditer(text):
        yield m.group(1)
    for m in md_link.finditer(text):
        yield m.group(1)


def _looks_like_path(token):
    if "://" in token or token.startswith("http"):
        return False
    if any(c in token for c in " {}$<>*?\"'|;&"):
        return False
    if "/" not in token and not token.startswith("."):
        return False
    return True


def _strip_line_suffix(token):
    return re.sub(r":\d+(-\d+)?(,\d+(-\d+)?)*$", "", token)


def _strip_fragment_and_query(token):
    # A markdown link's `#fragment` or `?query` is not part of the filesystem
    # path -- `docs/second-pc.md#prerequisites` names the same file as
    # `docs/second-pc.md`, so the suffix has to come off before resolution or
    # a live file with an anchor reads as a dead one.
    return re.split(r"[#?]", token, maxsplit=1)[0]


def _is_gitignored(root, relpath):
    # A path can be gitignored as a file or as a directory; `git check-ignore`
    # only honours a directory-only pattern (`node_modules/`) when the query
    # itself carries the trailing slash, so a plain miss is retried with one
    # before it counts as "not ignored".
    for candidate in (relpath, relpath + "/"):
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", candidate],
            cwd=root, capture_output=True,
        )
        if result.returncode == 0:
            return True
    return False


BACKTICK = re.compile(r"`([^`\n]+)`")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def find_dead_paths(root, path_scope):
    top_level = {p.name for p in root.iterdir() if p.name != ".git"}
    path_bases = [root, root / "backend", root / "frontend"]
    dead = []
    for f in path_scope:
        text = f.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            # `[`docs/x.md`](docs/x.md)` names one path but matches both
            # patterns, so findings are de-duplicated per line by the resolved
            # path -- two *different* dead paths on one line still count two.
            seen = set()
            for token in _candidates(line, BACKTICK, MD_LINK):
                if not _looks_like_path(token):
                    continue
                stripped = _strip_line_suffix(_strip_fragment_and_query(token)).removeprefix("./")
                if not stripped or stripped in seen:
                    continue
                seen.add(stripped)
                if stripped.startswith("/"):
                    # Someone else's namespace, not a filesystem claim. This
                    # is knowingly redundant on today's code -- `"/x/y".split(
                    # "/", 1)[0]` is `""`, which never matches `top_level`, so
                    # deleting this line moves no count -- but the docstring
                    # states the exclusion, so it is stated here too rather
                    # than left resting on the split's incidental behaviour.
                    continue
                first_seg = stripped.split("/", 1)[0]
                if first_seg not in top_level:
                    continue  # not a claim about this repo
                if any((base / stripped).exists() for base in path_bases):
                    continue
                if _is_gitignored(root, stripped):
                    continue  # expected-absent (generated or user-created), not dead
                dead.append((f, lineno, token))
    return dead


ROUTER_PREFIX = re.compile(r'APIRouter\(prefix="([^"]*)"')
ROUTE_DECORATOR = re.compile(r'@(?:router|app)\.(get|post|patch|put|delete)\("([^"]*)"')
DOC_ENDPOINT = re.compile(r"\b(GET|POST|PATCH|PUT|DELETE)\s+(/api/\S*)")


def _normalize_route(path):
    path = re.sub(r"\{[^}/]+\}", "{}", path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def _known_routes(root):
    api_files = sorted((root / "backend/app/api").glob("*.py"))
    main_file = root / "backend/app/main.py"
    if main_file.is_file():
        api_files.append(main_file)
    routes = set()
    first_segments = set()
    for f in api_files:
        text = f.read_text(encoding="utf-8")
        prefix_match = ROUTER_PREFIX.search(text)
        prefix = prefix_match.group(1) if prefix_match else ""
        for m in ROUTE_DECORATOR.finditer(text):
            method, path = m.group(1).upper(), m.group(2)
            full = _normalize_route(prefix + path)
            routes.add((method, full))
            segs = [s for s in full.split("/") if s]
            if segs:
                first_segments.add(segs[1] if segs[0] == "api" and len(segs) > 1 else segs[0])
    return routes, first_segments


def find_dead_endpoints(root, identifier_scope):
    routes, first_segments = _known_routes(root)
    dead = []
    for f in identifier_scope:
        text = f.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in DOC_ENDPOINT.finditer(line):
                method = m.group(1)
                path = m.group(2).split("?", 1)[0].rstrip("`)>,.\"'")
                norm = _normalize_route(path)
                segs = [s for s in norm.split("/") if s]
                first = segs[1] if len(segs) > 1 else ""
                if first not in first_segments:
                    continue
                if (method, norm) not in routes:
                    dead.append((f, lineno, f"{method} {path}"))
    return dead


EXCLUDE_DIRS = {".git", "node_modules", "__pycache__", "dist", ".venv"}
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ENV_VAR_SPAN = re.compile(r"`([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)`")


def _iter_source_files(root):
    source_roots = [root / "backend", root / "frontend/src", root / "scripts", root / "tests",
                     root / ".env.example", root / "docker-compose.yml"]
    for base in source_roots:
        if base.is_file():
            yield base
            continue
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_file() and not any(part in EXCLUDE_DIRS for part in p.parts):
                yield p


def _known_upper_identifiers(root):
    known = set()
    for p in _iter_source_files(root):
        try:
            text = p.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        for m in IDENTIFIER.finditer(text):
            known.add(m.group(0).upper())
    return known


def find_dead_env_vars(root, identifier_scope):
    known = _known_upper_identifiers(root)
    dead = []
    for f in identifier_scope:
        text = f.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in ENV_VAR_SPAN.finditer(line):
                token = m.group(1)
                if token.upper() not in known:
                    dead.append((f, lineno, token))
    return dead


def _live_source_kinds(root):
    models = root / "backend/app/models.py"
    if not models.is_file():
        return None
    for node in ast.walk(ast.parse(models.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ClassDef) and node.name == "SourceKind":
            return {
                stmt.value.value
                for stmt in node.body
                if isinstance(stmt, ast.Assign)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            }
    return None


def _historic_source_kinds(root):
    kinds = set()
    for f in sorted((root / "backend/alembic/versions").glob("*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            # An initial schema spells every kind inside `sa.Enum(..., name="sourcekind")`.
            if isinstance(node, ast.Call) and any(
                kw.arg == "name" and getattr(kw.value, "value", None) == "sourcekind"
                for kw in node.keywords
            ):
                kinds |= {
                    arg.value
                    for arg in node.args
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                }
            # A removal migration deletes rows by a `..._KIND = "..."` constant, the
            # only trace of a kind no enum listing ever contained.
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str) and any(
                    isinstance(t, ast.Name) and t.id.endswith("_KIND") for t in node.targets
                ):
                    kinds.add(node.value.value)
    return kinds


def _retired_connectors(root):
    live = _live_source_kinds(root)
    if live is None:
        return set()  # no enum to compare against; nothing is provably retired
    live_connectors = {kind.split("_", 1)[0] for kind in live}
    retired = {kind.split("_", 1)[0] for kind in _historic_source_kinds(root) - live}
    return retired - live_connectors


def find_dead_capabilities(root, identifier_scope):
    retired = _retired_connectors(root)
    if not retired:
        return []
    # Match any casing *except* all-lowercase: a connector name like `teams`
    # is also an ordinary English word, and docs write the connector itself
    # as a proper noun ("Teams conversations", "OneDrive files", a shouted
    # "TEAMS" in a heading) but use the bare lowercase word for ordinary
    # prose ("small teams of agents"). Anchoring on the one capitalized
    # spelling `w.capitalize()` produces would make this a word list again:
    # `onedrive` would only ever be looked for as `Onedrive`, never as the
    # `OneDrive` the docs actually write, silently costing coverage of the
    # vocabulary derived above.
    named = re.compile(r"\b(" + "|".join(sorted(re.escape(w) for w in retired)) + r")\b", re.I)
    dead = []
    for f in identifier_scope:
        text = f.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            # One finding per line, however many times it names the connector.
            match = next(
                (m for m in named.finditer(line) if m.group(0) != m.group(0).lower()), None
            )
            if match:
                dead.append((f, lineno, match.group(0)))
    return dead


MODULE_REF = re.compile(r"-m\s+([A-Za-z_][A-Za-z0-9_.]*)")


def find_dead_commands(root, identifier_scope):
    dead = []
    for f in identifier_scope:
        text = f.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in MODULE_REF.finditer(line):
                module = m.group(1)
                rel = pathlib.Path(*module.split("."))
                candidate_file = root / "backend" / rel.with_suffix(".py")
                candidate_pkg = root / "backend" / rel / "__init__.py"
                if not candidate_file.is_file() and not candidate_pkg.is_file():
                    dead.append((f, lineno, f"-m {module}"))
    return dead


def _doc_scopes(root):
    companion_dir = root / ".companion"
    doc_files = [root / "README.md"]
    if (root / "docs").is_dir():
        doc_files += sorted((root / "docs").rglob("*.md"))
    path_scope = list(doc_files)
    if companion_dir.is_dir():
        path_scope += sorted(p for p in companion_dir.glob("*.md") if p.name != "harness-notes.md")
    return path_scope, doc_files


def run(root):
    """Returns (total_count, debug_lines) for the given repo root."""
    path_scope, identifier_scope = _doc_scopes(root)
    debug_lines = []
    total = 0
    for label, finder, args in (
        ("path", find_dead_paths, (root, path_scope)),
        ("endpoint", find_dead_endpoints, (root, identifier_scope)),
        ("env var", find_dead_env_vars, (root, identifier_scope)),
        ("command", find_dead_commands, (root, identifier_scope)),
        ("capability", find_dead_capabilities, (root, identifier_scope)),
    ):
        results = finder(*args)
        for f, lineno, token in results:
            debug_lines.append(f"  dead doc {label} {token!r} ({f.relative_to(root)}:{lineno})")
        total += len(results)
    return total, debug_lines


def main(argv):
    root = pathlib.Path(argv[1] if len(argv) > 1 else ".").resolve()
    total, debug_lines = run(root)
    for line in debug_lines:
        print(line, file=sys.stderr)
    print(total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
