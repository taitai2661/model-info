import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A copy of the source data + schemas that tests may mutate freely."""
    import shutil

    shutil.copytree(ROOT / "data", tmp_path / "data")
    shutil.copytree(ROOT / "schemas", tmp_path / "schemas")
    return tmp_path
