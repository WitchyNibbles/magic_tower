"""Score ``should_promote`` against a labeled sample of the owner's real mail.

Usage::

    cd backend
    uv run python -m app.tools.heuristic_eval --sample ~/.magic-tower/labeled-sample.json \\
        [--owner-address you@contoso.com --owner-address you@contoso.onmicrosoft.com]

Runs from the JSON sample file alone: no database, no Graph credentials, so it
works on this machine and on the one that has Outlook access. Four sample states,
each printed and exited differently so none can be mistaken for another:

* absent (no file at the path) -- prints a message and exits 0, so CI and a
  machine that has never synced real mail both stay green;
* present but with no labeled rows (an empty array, or every row's ``label`` is
  still ``null``) -- prints the row count and exits 0; there is nothing to score
  yet, but the file is not missing;
* present but not a valid labeled sample (bad JSON, wrong shape, a row missing a
  field) -- prints the problem to stderr and exits 1, because this is the
  owner's mistake to fix, not a reason to look green;
* present, valid, and labeled -- prints counts, precision, recall, and the
  misclassified rows by id, and exits 0.

``--owner-address`` is optional and repeatable; without it, rule 4 of
``should_promote`` (mail the owner was only copied on) is never exercised, the
same way a live sync with no profile skips it -- a missing address costs recall,
never a crash.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from ..services.promotion import should_promote
from .heuristic_sample import DEFAULT_SAMPLE_PATH, SampleSchemaError, load_sample, signal_from_row


def evaluate(rows: list[dict[str, Any]], owner_addresses: tuple[str, ...] = ()) -> dict[str, Any]:
    """Confusion-matrix counts, precision, recall, and misclassified ids over the labeled rows.

    Rows whose ``label`` is still ``null`` are counted but not scored. Precision
    and recall are ``None`` -- not zero -- when their denominator is zero, so an
    empty confusion matrix cannot masquerade as a perfect or a failing one.
    """
    labeled = [row for row in rows if row.get("label") is not None]
    true_positives = false_positives = true_negatives = false_negatives = 0
    misclassified: list[str] = []
    for row in labeled:
        predicted = should_promote(signal_from_row(row), owner_addresses)
        actual = bool(row["label"])
        if predicted and actual:
            true_positives += 1
        elif predicted and not actual:
            false_positives += 1
            misclassified.append(row["id"])
        elif actual and not predicted:
            false_negatives += 1
            misclassified.append(row["id"])
        else:
            true_negatives += 1
    predicted_positive = true_positives + false_positives
    actual_positive = true_positives + false_negatives
    return {
        "total_rows": len(rows),
        "labeled_rows": len(labeled),
        "true_positives": true_positives,
        "false_positives": false_positives,
        "true_negatives": true_negatives,
        "false_negatives": false_negatives,
        "precision": (true_positives / predicted_positive) if predicted_positive else None,
        "recall": (true_positives / actual_positive) if actual_positive else None,
        "misclassified": misclassified,
    }


def _rate(value: float | None, empty_reason: str) -> str:
    return f"{value:.1%}" if value is not None else f"n/a ({empty_reason})"


def _format_report(result: dict[str, Any]) -> str:
    lines = [
        f"labeled rows: {result['labeled_rows']} of {result['total_rows']}",
        f"true positives: {result['true_positives']}  false positives: {result['false_positives']}",
        f"true negatives: {result['true_negatives']}  false negatives: {result['false_negatives']}",
        f"precision: {_rate(result['precision'], 'nothing was predicted promote')}",
        f"recall: {_rate(result['recall'], 'nothing was labeled promote')}",
        "misclassified rows: " + (", ".join(result["misclassified"]) or "none"),
    ]
    return "\n".join(lines)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score should_promote against a labeled sample of real mail.")
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE_PATH,
                         help="path to the labeled sample JSON file (default: %(default)s)")
    parser.add_argument("--owner-address", action="append", default=[], dest="owner_addresses",
                         help="an address the owner is known by; repeatable")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        rows = load_sample(args.sample)
    except SampleSchemaError as error:
        print(f"labeled sample at {args.sample} is not usable: {error}", file=sys.stderr)
        return 1
    if rows is None:
        print(f"no labeled sample at {args.sample}; nothing to evaluate "
              "(run heuristic_export after a sync, then label it)")
        return 0
    result = evaluate(rows, tuple(args.owner_addresses))
    if result["labeled_rows"] == 0:
        print(f"sample at {args.sample} has {result['total_rows']} row(s) but none are labeled yet; "
              "nothing to evaluate")
        return 0
    print(_format_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
