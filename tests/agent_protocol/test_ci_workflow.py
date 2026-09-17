"""Guards the CI workflow that is supposed to enforce this whole test bar.

Structural checks over ``.github/workflows/ci.yml`` catch regressions a quick
skim would miss -- e.g. a test job that quietly drops ``../tests/agent_protocol``
from its ``pytest`` invocation, or a workflow that stops triggering on pull
requests. There is no runner and no ``actionlint`` here, so this is the only
mechanical check the workflow gets; that it actually goes green on GitHub is
manual.

Lives beside the agent-protocol suite (not under ``backend/tests``) because
``backend/tests/conftest.py`` sets up a database and a session env before
anything else is collected -- work this workflow-parsing test has no need of.
"""

from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).parents[2] / ".github" / "workflows" / "ci.yml"


def _load_workflow() -> dict:
    """Parse the workflow file, failing with a clear message if it is absent."""
    assert WORKFLOW_PATH.is_file(), f"missing {WORKFLOW_PATH}"
    return yaml.safe_load(WORKFLOW_PATH.read_text())


def _run_steps(job: dict) -> list[dict]:
    """Every step in a job that has a ``run:`` command, in declared order."""
    return [step for step in job.get("steps", []) if "run" in step]


def test_workflow_triggers_on_push_and_pull_request():
    workflow = _load_workflow()
    # PyYAML follows YAML 1.1, so a bare ``on:`` key parses as the boolean
    # ``True``, not the string ``"on"`` -- look the trigger map up by either.
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None, "workflow has no 'on' trigger section"
    assert "push" in triggers, "workflow does not trigger on push"
    assert "pull_request" in triggers, "workflow does not trigger on pull_request"


def test_a_job_runs_the_full_backend_and_agent_protocol_suite_from_backend():
    workflow = _load_workflow()
    jobs = workflow.get("jobs", {})
    test_jobs = [
        job
        for job in jobs.values()
        if any(
            "uv run pytest" in step["run"]
            and "tests" in step["run"]
            and "../tests/agent_protocol" in step["run"]
            for step in _run_steps(job)
        )
    ]
    assert test_jobs, (
        "no job runs 'uv run pytest tests ../tests/agent_protocol'; "
        f"jobs found: {list(jobs)}"
    )
    test_job = test_jobs[0]

    step_uses = [step.get("uses", "") for step in test_job["steps"]]
    assert any(use.startswith("actions/checkout@") for use in step_uses), (
        "test job never checks out the repository"
    )
    assert any(use.startswith("astral-sh/setup-uv@") for use in step_uses), (
        "test job never installs uv via astral-sh/setup-uv"
    )

    setup_uv_step = next(
        step for step in test_job["steps"] if step.get("uses", "").startswith("astral-sh/setup-uv@")
    )
    assert str(setup_uv_step.get("with", {}).get("python-version")) == "3.12", (
        "test job does not pin Python 3.12, which backend/.python-version requires"
    )

    pytest_step = next(
        step for step in _run_steps(test_job) if "uv run pytest" in step["run"]
    )
    assert pytest_step.get("working-directory") == "backend", (
        "the pytest step must run with working-directory: backend, or the "
        'cwd-relative env_file=".env" in app/config.py loads the wrong .env'
    )


def test_a_job_builds_the_docker_compose_stack():
    workflow = _load_workflow()
    jobs = workflow.get("jobs", {})
    build_jobs = [
        job
        for job in jobs.values()
        if any("docker compose build" in step["run"] for step in _run_steps(job))
    ]
    assert build_jobs, f"no job runs 'docker compose build'; jobs found: {list(jobs)}"
