#!/usr/bin/env python3
"""Dead-documentation checker for ``scripts/deadcode.sh``'s dead-code gate.

Flags four kinds of documentation reference that name something this repo does
not actually have: a file path (backtick-quoted or a markdown-link target), a
`METHOD /api/...` endpoint, a bare `ENV_VAR_NAME`, and a `-m module.path`
command.

Scope decisions, made explicit here because each cost a false positive to find:

* ``.companion/harness-notes.md`` is excluded entirely. Its own first line says
  it documents "the project-companion repo" -- a different codebase -- so every
  path or identifier in it is a claim about code this checker cannot see.
* Endpoint, env-var and command checks are further scoped to ``README.md`` and
  ``docs/`` only. The rest of ``.companion/*.md`` is a session-by-session
  historical log (backlog, progress, plan, contract, explore) that narrates
  other systems' APIs (a Freshservice/Jira connector sketch in ``explore.md``)
  and even the harness's own internal names inline in prose (``backlog.md``'s
  `TEST_PATH` entry names the *manager's* regex, not this repo's) --
  indistinguishable from a real dead reference by a checker this simple. File
  paths are still checked across all of ``.companion/*.md`` (minus
  harness-notes.md): a broken path is a narrower, more objective claim than an
  endpoint or a bare identifier, so it stays in scope there.
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

Known false positives (accepted, same class as vulture's pydantic-field noise
documented in the contract): a doc line that *asserts an absence*
(``.companion/progress.md``'s "there is no `frontend/.gitignore`") reads as a
positive existence claim to this checker, which does no negation detection;
and a bare identifier that names the *manager's own harness*, not this repo,
inside an otherwise in-scope file (``.companion/backlog.md``'s `TEST_PATH`)
cannot be told apart from a real dead reference without knowing which repo
each backlog entry's code is even in.
"""
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
            for token in _candidates(line, BACKTICK, MD_LINK):
                if not _looks_like_path(token):
                    continue
                stripped = _strip_line_suffix(token).lstrip("./")
                if not stripped:
                    continue
                first_seg = stripped.split("/", 1)[0]
                if "/" in stripped:
                    if first_seg not in top_level:
                        continue  # not a claim about this repo
                elif not stripped.startswith("."):
                    continue
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
