"""Scoring ``should_promote`` against a labeled sample, and the four sample states.

``evaluate`` must call the real heuristic, not a copy of its rules: a test that
stubbed ``should_promote`` and still passed would prove nothing (the same trap
T05's promotion rules fell into before they had real coverage), so one test below
asserts the identity of the imported function rather than only its behaviour.

Every row here is synthetic, in the same spirit as ``tests/test_promotion.py``:
the labeled sample of the owner's real mail this tool measures never enters the
repository.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.services.promotion import should_promote as real_should_promote
from app.tools import heuristic_eval
from app.tools.heuristic_eval import evaluate, main
from app.tools.heuristic_sample import load_sample

OWNER = "owner@contoso.com"
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _row(**overrides: Any) -> dict[str, Any]:
    """A direct colleague email correctly labeled ``True`` (should be promoted), by default."""
    return {
        "id": "outlook:direct-1", "source_kind": "outlook_email",
        "subject": "Can you review the migration plan?", "excerpt": "please take a look",
        "sender": "colleague@contoso.com", "sender_kind": "user",
        "to_recipients": [OWNER], "headers": {},
        "url": "https://outlook.office.com/mail/direct-1", "observed_at": "2026-09-18T08:30:00Z",
        "label": True,
        **overrides,
    }


def _newsletter(**overrides: Any) -> dict[str, Any]:
    """Correctly labeled ``False``: the sender rule alone should skip it."""
    defaults = {"id": "outlook:newsletter-1", "sender": "newsletter@vendor.example", "label": False}
    return _row(**{**defaults, **overrides})


def _bot(**overrides: Any) -> dict[str, Any]:
    """Correctly labeled ``False``: an application, not a person, posted it."""
    defaults = {"id": "outlook:bot-1", "sender": None,
                "sender_kind": "application", "to_recipients": [], "label": False}
    return _row(**{**defaults, **overrides})


# --- evaluate() arithmetic -------------------------------------------------


def test_evaluate_imports_the_real_heuristic_not_a_reimplementation() -> None:
    assert heuristic_eval.should_promote is real_should_promote


def test_evaluate_scores_a_mixed_confusion_matrix_by_id() -> None:
    rows = [
        _row(),  # a real TP: sender is a person, addressed to the owner, label True
        _newsletter(),  # a real TN: automated sender, label False
        _bot(),  # a real TN: application sender_kind, label False
        # Mislabeled True on an automated sender: heuristic correctly predicts
        # False, so this is a false negative -- the sample says "promote" and the
        # heuristic disagrees.
        _row(id="outlook:mislabeled-fn", sender="marketing@vendor.example", label=True),
        # Mislabeled False on a message that is genuinely addressed to the owner
        # from a person: heuristic correctly predicts True, so this is a false
        # positive -- the sample says "skip" and the heuristic disagrees.
        _row(id="outlook:mislabeled-fp", label=False),
    ]

    result = evaluate(rows, owner_addresses=(OWNER,))

    assert result["total_rows"] == 5
    assert result["labeled_rows"] == 5
    assert result["true_positives"] == 1
    assert result["false_positives"] == 1
    assert result["true_negatives"] == 2
    assert result["false_negatives"] == 1
    assert result["precision"] == pytest.approx(0.5)
    assert result["recall"] == pytest.approx(0.5)
    assert set(result["misclassified"]) == {"outlook:mislabeled-fn", "outlook:mislabeled-fp"}


def test_evaluate_ignores_unlabeled_rows() -> None:
    result = evaluate([_row(), _row(id="outlook:unlabeled", label=None)], owner_addresses=(OWNER,))

    assert result["total_rows"] == 2
    assert result["labeled_rows"] == 1
    assert result["true_positives"] == 1


def test_evaluate_reports_no_precision_when_nothing_is_predicted_promote() -> None:
    """Every row here is an automated sender the heuristic will always skip."""
    rows = [_newsletter(), _newsletter(id="outlook:newsletter-2")]

    result = evaluate(rows, owner_addresses=(OWNER,))

    assert result["true_positives"] == 0
    assert result["false_positives"] == 0
    assert result["precision"] is None
    assert result["recall"] is None


def test_evaluate_reports_no_recall_when_no_row_is_labeled_promote() -> None:
    """A predicted false positive with no actual positive anywhere in the sample."""
    rows = [_row(label=False), _newsletter()]

    result = evaluate(rows, owner_addresses=(OWNER,))

    assert result["false_positives"] == 1
    assert result["false_negatives"] == 0
    assert result["recall"] is None
    assert result["precision"] == pytest.approx(0.0)


def test_evaluate_without_owner_addresses_never_exercises_the_cc_only_rule() -> None:
    """Mirrors ``should_promote``: a missing profile costs recall, never a crash."""
    only_copied = _row(to_recipients=["someone-else@contoso.com"], label=False)

    result = evaluate([only_copied], owner_addresses=())

    # With no owner address known, rule 4 cannot fire, so this is predicted True
    # against a label of False: a false positive, not a true negative.
    assert result["false_positives"] == 1
    assert result["true_negatives"] == 0


# --- main(): the four sample states -----------------------------------------


def test_main_exits_zero_with_a_message_when_the_sample_is_absent(tmp_path, capsys) -> None:
    missing = tmp_path / "labeled-sample.json"

    exit_code = main(["--sample", str(missing)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert str(missing) in out
    assert "nothing to evaluate" in out


def test_main_exits_zero_with_a_message_when_the_sample_is_an_empty_array(tmp_path, capsys) -> None:
    sample = tmp_path / "labeled-sample.json"
    sample.write_text("[]")

    exit_code = main(["--sample", str(sample)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "0 row(s)" in out
    assert "nothing to evaluate" in out


def test_main_exits_zero_with_a_message_when_no_row_is_labeled_yet(tmp_path, capsys) -> None:
    sample = tmp_path / "labeled-sample.json"
    sample.write_text(json.dumps([_row(label=None), _newsletter(label=None)]))

    exit_code = main(["--sample", str(sample)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "2 row(s)" in out
    assert "none are labeled yet" in out


def test_main_exits_nonzero_when_the_sample_is_not_valid_json(tmp_path, capsys) -> None:
    sample = tmp_path / "labeled-sample.json"
    sample.write_text("{not json")

    exit_code = main(["--sample", str(sample)])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "not valid JSON" in err


def test_main_exits_nonzero_when_the_sample_is_not_a_json_array(tmp_path, capsys) -> None:
    sample = tmp_path / "labeled-sample.json"
    sample.write_text(json.dumps({"not": "a list"}))

    exit_code = main(["--sample", str(sample)])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "JSON array" in err


def test_main_exits_nonzero_when_a_row_is_missing_a_required_field(tmp_path, capsys) -> None:
    sample = tmp_path / "labeled-sample.json"
    broken_row = _row()
    del broken_row["sender"]
    sample.write_text(json.dumps([broken_row]))

    exit_code = main(["--sample", str(sample)])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "missing field" in err
    assert "sender" in err


def test_main_exits_nonzero_when_a_label_is_not_true_false_or_null(tmp_path, capsys) -> None:
    sample = tmp_path / "labeled-sample.json"
    sample.write_text(json.dumps([_row(label="yes")]))

    exit_code = main(["--sample", str(sample)])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "label" in err


def test_main_prints_precision_recall_and_misclassified_rows_for_a_healthy_sample(tmp_path, capsys) -> None:
    sample = tmp_path / "labeled-sample.json"
    sample.write_text(json.dumps([_row(), _newsletter(), _row(id="outlook:missed", sender="marketing@x.example", label=True)]))

    exit_code = main(["--sample", str(sample), "--owner-address", OWNER])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "true positives: 1" in out
    assert "false negatives: 1" in out
    assert "precision: 100.0%" in out
    assert "recall: 50.0%" in out
    assert "outlook:missed" in out


def test_main_uses_the_shared_sample_loader_not_a_reimplementation() -> None:
    """``main``'s exit-1 path is only meaningful if it is fed by the real loader."""
    assert heuristic_eval.load_sample is load_sample


def test_load_sample_reads_the_file_as_utf8_whatever_the_ambient_encoding_is(tmp_path) -> None:
    """Nothing but an explicit encoding decides how the sample is decoded.

    Without one, the locale of whatever machine opens the file does -- and the
    second PC's need not be UTF-8 (a Windows console or a bare ``LC_ALL=C`` service
    account is not). An accented subject then raises ``UnicodeDecodeError`` and the
    whole labeled sample is unreadable, on the one machine that has the real mail.

    A running interpreter cannot change its own ambient encoding, so this reads the
    sample in a subprocess whose locale makes that default ASCII: there, a call site
    without an explicit encoding really does fail.
    """
    sample = tmp_path / "labeled-sample.json"
    sample.write_bytes(json.dumps([_row(subject="\u00c1 review")], ensure_ascii=False).encode("utf-8"))
    reader = tmp_path / "read_one_subject.py"
    reader.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "from app.tools.heuristic_sample import load_sample\n"
        # ``ascii`` so the result survives this subprocess's ASCII stdout too, and
        # the assertion below is about what was decoded, not how it was printed.
        "print(ascii(load_sample(Path(sys.argv[1]))[0][\"subject\"]))\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(reader), str(sample)],
        cwd=BACKEND_DIR,
        env={**os.environ, "PYTHONPATH": str(BACKEND_DIR),
             "LC_ALL": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"},
        capture_output=True,
        text=True,
        timeout=25,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ascii("\u00c1 review")


# --- MAGIC_TOWER_REQUIRE_SAMPLE strict mode ---------------------------------


def test_main_exits_zero_when_the_sample_is_absent_and_strict_mode_is_unset(tmp_path, monkeypatch, capsys) -> None:
    """Default behaviour is unchanged: AC11's lenient path must keep passing."""
    monkeypatch.delenv("MAGIC_TOWER_REQUIRE_SAMPLE", raising=False)
    missing = tmp_path / "labeled-sample.json"

    exit_code = main(["--sample", str(missing)])

    assert exit_code == 0


def test_main_exits_nonzero_when_the_sample_is_absent_and_strict_mode_is_set(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("MAGIC_TOWER_REQUIRE_SAMPLE", "1")
    missing = tmp_path / "labeled-sample.json"

    exit_code = main(["--sample", str(missing)])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert str(missing) in err
    assert "MAGIC_TOWER_REQUIRE_SAMPLE" in err


def test_main_exits_nonzero_when_no_row_is_labeled_and_strict_mode_is_set(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("MAGIC_TOWER_REQUIRE_SAMPLE", "1")
    sample = tmp_path / "labeled-sample.json"
    sample.write_text(json.dumps([_row(label=None), _newsletter(label=None)]))

    exit_code = main(["--sample", str(sample)])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert str(sample) in err
    assert "MAGIC_TOWER_REQUIRE_SAMPLE" in err


def test_main_treats_a_blank_require_sample_value_as_lenient(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("MAGIC_TOWER_REQUIRE_SAMPLE", "")
    missing = tmp_path / "labeled-sample.json"

    exit_code = main(["--sample", str(missing)])

    assert exit_code == 0


def test_main_treats_a_zero_require_sample_value_as_lenient(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("MAGIC_TOWER_REQUIRE_SAMPLE", "0")
    missing = tmp_path / "labeled-sample.json"

    exit_code = main(["--sample", str(missing)])

    assert exit_code == 0


def test_main_still_reports_a_healthy_labeled_sample_when_strict_mode_is_set(tmp_path, monkeypatch, capsys) -> None:
    """Strict mode changes the silent-pass cases, not the already-scored one."""
    monkeypatch.setenv("MAGIC_TOWER_REQUIRE_SAMPLE", "1")
    sample = tmp_path / "labeled-sample.json"
    sample.write_text(json.dumps([_row(), _newsletter()]))

    exit_code = main(["--sample", str(sample), "--owner-address", OWNER])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "true positives: 1" in out


def test_the_committed_synthetic_example_is_a_valid_labeled_sample(capsys) -> None:
    """The schema reference this task commits must stay a real, loadable sample.

    Obviously synthetic (``example.test`` addresses, ``EXAMPLE:`` subjects) --
    this is the file the second PC's owner is pointed at for the row shape, never
    real mail.
    """
    example_path = Path(__file__).resolve().parents[1] / "app" / "tools" / "labeled-sample.example.json"

    exit_code = main(["--sample", str(example_path), "--owner-address", "owner@example.test"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "labeled rows: 2 of 3" in out
