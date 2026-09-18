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

``--allow-sender`` is the same allowlist ``PROMOTION_ALLOWLISTED_SENDERS`` gives a
live sync, passed here so a score matches what the sync would decide.

``--owner-address`` is optional and repeatable; without it, rule 4 of
``should_promote`` (mail the owner was only copied on) is never exercised, the
same way a live sync with no profile skips it -- a missing address costs recall,
never a crash.

Setting ``MAGIC_TOWER_REQUIRE_SAMPLE=1`` turns the two silent-pass states above
into hard failures (a message on stderr naming the sample path, exit 1), because
a second PC's own eval run is meant to prove the heuristic was actually checked,
not merely that the command ran:

* absent stays a hard failure under strict mode -- a second PC that never ran
  ``heuristic_export`` cannot look the same as one that did;
* present-but-unlabeled is *also* a hard failure under strict mode, for the
  same reason: an exported-but-never-labeled sample is exactly as silent as a
  missing one is, and the owner's complaint this flag exists to fix is a second
  PC that "passes" without anyone having looked at a single row;
* present-but-invalid already exits 1 in both modes, so strict mode changes
  nothing there;
* present, valid, and labeled always exits 0 and prints the report, in both
  modes -- strict mode only raises the floor, it never lowers the bar for an
  already-real result.

Unset, empty, or ``"0"`` keeps today's lenient behaviour (exit 0), so CI and a
machine that has never synced real mail both stay green by default; strict mode
is opt-in and the default must never change.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from ..services.promotion import should_promote
from .heuristic_sample import DEFAULT_SAMPLE_PATH, SampleSchemaError, load_sample, signal_from_row

REQUIRE_SAMPLE_ENV_VAR = "MAGIC_TOWER_REQUIRE_SAMPLE"


def evaluate(rows: list[dict[str, Any]], owner_addresses: tuple[str, ...] = (),
             allowlisted_senders: tuple[str, ...] = ()) -> dict[str, Any]:
    """Confusion-matrix counts, precision, recall, and misclassified ids over the labeled rows.

    Rows whose ``label`` is still ``null`` are counted but not scored. Precision
    and recall are ``None`` -- not zero -- when their denominator is zero, so an
    empty confusion matrix cannot masquerade as a perfect or a failing one.
    """
    labeled = [row for row in rows if row.get("label") is not None]
    true_positives = false_positives = true_negatives = false_negatives = 0
    misclassified: list[str] = []
    for row in labeled:
        predicted = should_promote(signal_from_row(row), owner_addresses, allowlisted_senders)
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


def _require_sample() -> bool:
    """Whether ``MAGIC_TOWER_REQUIRE_SAMPLE`` opts this run into strict mode.

    Unset, empty, or ``"0"`` is lenient (today's default); any other value is
    strict. There is no bare ``bool(os.environ.get(...))`` here on purpose --
    that would make ``MAGIC_TOWER_REQUIRE_SAMPLE=0`` strict too, which would
    make CI's unset-by-default assumption one environment variable away from
    breaking.
    """
    return os.environ.get(REQUIRE_SAMPLE_ENV_VAR, "") not in ("", "0")


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
    parser.add_argument("--allow-sender", action="append", default=[], dest="allowlisted_senders",
                         help="an address whose mail is always work, whatever the rules say; repeatable")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    strict = _require_sample()
    try:
        rows = load_sample(args.sample)
    except SampleSchemaError as error:
        print(f"labeled sample at {args.sample} is not usable: {error}", file=sys.stderr)
        return 1
    if rows is None:
        if strict:
            print(f"{REQUIRE_SAMPLE_ENV_VAR}=1 requires a labeled sample, but none exists at {args.sample}",
                  file=sys.stderr)
            return 1
        print(f"no labeled sample at {args.sample}; nothing to evaluate "
              "(run heuristic_export after a sync, then label it)")
        return 0
    result = evaluate(rows, tuple(args.owner_addresses), tuple(args.allowlisted_senders))
    if result["labeled_rows"] == 0:
        if strict:
            print(f"{REQUIRE_SAMPLE_ENV_VAR}=1 requires a labeled sample, but {args.sample} has "
                  f"{result['total_rows']} row(s) and none are labeled", file=sys.stderr)
            return 1
        print(f"sample at {args.sample} has {result['total_rows']} row(s) but none are labeled yet; "
              "nothing to evaluate")
        return 0
    print(_format_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
