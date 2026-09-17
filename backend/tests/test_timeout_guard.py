"""Guards the hang watchdog that ``[tool.pytest.ini_options]`` arms for this suite."""

import threading


def test_the_suite_defaults_to_a_thread_based_hang_timeout(pytestconfig):
    """Ask the running session for its effective settings, not ``pyproject.toml``."""
    assert pytestconfig.pluginmanager.hasplugin("timeout"), (
        "pytest-timeout is missing, so a hanging test would block the suite forever"
    )
    configured = pytestconfig.getini("timeout")
    assert configured and float(configured) > 0, (
        f"no default timeout is configured (got {configured!r}); "
        "a hang would only be caught when someone passes --timeout by hand"
    )
    assert pytestconfig.getini("timeout_method") == "thread", (
        "only the thread method can interrupt a test blocked inside a C-level call"
    )


def test_this_very_test_is_watched_by_a_running_timer_thread(request):
    """The configured default has to reach individual tests, this one included.

    ``pytest_timeout`` names the ``threading.Timer`` it starts for each item after
    the item, so a live thread of that name proves the watchdog really is armed --
    waiting for the 30s default to fire would cost more than the whole suite.
    """
    watchdogs = [
        thread
        for thread in threading.enumerate()
        if thread.name == f"pytest_timeout {request.node.nodeid}"
    ]
    assert len(watchdogs) == 1, (
        "no timeout thread is watching this test, so a hang here would never be "
        f"dumped and killed; running threads: {[t.name for t in threading.enumerate()]}"
    )
    assert watchdogs[0].interval > 0, "the watchdog would fire immediately or never"
