"""Guards that the wheel ships exactly the ``app`` package, whatever else lives in ``backend/``.

``pyproject.toml`` once relied on setuptools' flat-layout auto-discovery, which
enumerates every importable top-level directory. That works only while ``app`` is
the sole such directory: the moment a second one appears (``alembic/`` did), every
``uv sync`` / ``uv run`` fails with "Multiple top-level packages discovered". The
directive that pins the package list has to stay explicit, and this proves it by
building against a tree that deliberately contains a stray extra package.
"""

import shutil
import subprocess
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _build_wheel(project_dir: Path) -> Path:
    """Build a wheel for ``project_dir`` with the project's own toolchain."""
    dist_dir = project_dir / "dist"
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr
    return next(dist_dir.glob("*.whl"))


def _top_level_packages(wheel: Path) -> set[str]:
    """Package directories in ``wheel``, ignoring its own ``.dist-info`` metadata."""
    with zipfile.ZipFile(wheel) as archive:
        roots = {name.split("/")[0] for name in archive.namelist()}
    return {root for root in roots if not root.endswith(".dist-info")}


def test_wheel_ships_only_app_even_with_a_stray_top_level_directory(tmp_path):
    project_dir = tmp_path / "backend"
    project_dir.mkdir()
    shutil.copy(BACKEND_DIR / "pyproject.toml", project_dir)
    shutil.copytree(BACKEND_DIR / "app", project_dir / "app", ignore=shutil.ignore_patterns("__pycache__"))
    (project_dir / "stray").mkdir()
    (project_dir / "stray" / "__init__.py").write_text("")

    wheel = _build_wheel(project_dir)

    assert _top_level_packages(wheel) == {"app"}, (
        "package discovery is implicit again; a second top-level directory under "
        "backend/ breaks every `uv sync`/`uv run`"
    )
