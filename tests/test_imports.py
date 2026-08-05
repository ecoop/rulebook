"""Import-everything guard.

CI imports the `rulebook` package, but nothing imported `api/` or `scripts/`
— which is how a stale `llm_guardrails` import survived in
`scripts/vision_extract.py` after the #5 migration (a latent ImportError that
neither compileall nor `import rulebook` caught). These tests import every
module under src/, api/, and scripts/, so a rename-miss or broken import in
any of them fails CI.
"""

import importlib
import pkgutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_SCRIPT_DIR = REPO / "scripts"


def _package_modules(pkg_name: str) -> list[str]:
    """The package plus every submodule name under it."""
    pkg = importlib.import_module(pkg_name)
    names = [pkg_name]
    if hasattr(pkg, "__path__"):
        for info in pkgutil.walk_packages(pkg.__path__, prefix=pkg_name + "."):
            names.append(info.name)
    return names


_SCRIPTS = sorted(p.stem for p in _SCRIPT_DIR.glob("*.py") if p.stem != "__init__")


@pytest.mark.parametrize("module", _package_modules("rulebook"))
def test_import_rulebook_module(module):
    importlib.import_module(module)


@pytest.mark.parametrize("module", _package_modules("api"))
def test_import_api_module(module):
    importlib.import_module(module)


@pytest.mark.parametrize("stem", _SCRIPTS)
def test_import_script(stem):
    # scripts/ is on sys.path via pytest's `pythonpath` setting (see pyproject).
    # This is the guard that would have caught the stale llm_guardrails import
    # left in scripts/vision_extract.py after the #5 migration.
    importlib.import_module(stem)
