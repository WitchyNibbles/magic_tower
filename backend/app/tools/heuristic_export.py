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
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import SessionLocal
from ..models import Source
from .heuristic_sample import DEFAULT_SAMPLE_PATH, row_from_source


def export_rows(db: Session) -> list[dict]:
    """One unlabeled row per ``Source``, oldest first, so labeling has a stable order."""
    query = select(Source).options(selectinload(Source.signal_context)).order_by(Source.observed_at)
    return [row_from_source(source) for source in db.scalars(query)]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a labeled-sample file for the heuristic eval tool.")
    parser.add_argument("--output", type=Path, default=DEFAULT_SAMPLE_PATH,
                         help="where to write the sample (default: %(default)s)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db = SessionLocal()
    try:
        rows = export_rows(db)
    finally:
        db.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} row(s) to {args.output}; label each row's \"label\" field "
          "(true/false) and run heuristic_eval", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
