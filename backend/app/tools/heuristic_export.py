"""Export a labeled-sample file from the local database, for hand labeling.

Usage::

    cd backend
    DATABASE_URL=sqlite:///./workboard.db uv run python -m app.tools.heuristic_export \\
        --output ~/.magic-tower/labeled-sample.json

Reads every ``Source`` row a sync has written and writes one row per signal with
the fields a human needs to judge it -- subject and excerpt included, decrypted,
since the owner chose to keep full content on this machine -- plus an empty
``label`` field. Run it after ``POST /api/sync``, never instead of it: this tool
never talks to Microsoft Graph. See ``heuristic_sample.py`` for the row schema and
``heuristic_eval.py`` for what reads the file back once it is labeled.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session, selectinload

from ..database import SessionLocal
from ..models import Source
from .heuristic_sample import DEFAULT_SAMPLE_PATH, row_from_source


def export_rows(db: Session) -> list[dict]:
    """One unlabeled row per ``Source``, oldest first, so labeling has a stable order."""
    query = select(Source).options(selectinload(Source.signal_context)).order_by(Source.observed_at)
    return [row_from_source(source) for source in db.scalars(query)]


def _write_sample(path: Path, rows: list[dict]) -> None:
    """Write the sample where only its owner can read it.

    The rows are the owner's real mail in cleartext, and a second PC is often a
    shared or managed one, so neither the default 0644 of a fresh file nor the mode
    an earlier run left behind is good enough; the umask cannot loosen either.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    os.chmod(path, 0o600)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a labeled-sample file for the heuristic eval tool.")
    parser.add_argument("--output", type=Path, default=DEFAULT_SAMPLE_PATH,
                         help="where to write the sample (default: %(default)s)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db = SessionLocal()
    # The database actually opened, not the environment's idea of it, so the message
    # is true whatever set it. ``URL.__str__`` masks a password if the URL carries one.
    database_url = db.get_bind().url
    try:
        rows = export_rows(db)
    except DatabaseError as error:
        # An absent file, an unmigrated schema and a wrong URL all arrive here, and
        # all three are the owner pointing the tool at the wrong database or at one
        # no sync has prepared. Which exception says so depends on the driver --
        # SQLite raises ``OperationalError`` for all three, Postgres raises
        # ``ProgrammingError`` for the unmigrated schema -- and ``DatabaseError`` is
        # their common base. Name the two remedies instead of raising a traceback.
        print(f"cannot read the database at {database_url}: {error.orig}\n"
              "Set DATABASE_URL to the database the sync wrote to (a local checkout uses "
              "sqlite:///./workboard.db), and bring it to head with `alembic upgrade head`.",
              file=sys.stderr)
        return 1
    finally:
        db.close()
    _write_sample(args.output, rows)
    print(f"wrote {len(rows)} row(s) to {args.output}; label each row's \"label\" field "
          "(true/false) and run heuristic_eval", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
