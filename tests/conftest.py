from pathlib import Path

import pytest

from membergraph.tools.warehouse import Warehouse

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "fixtures"


@pytest.fixture(scope="session")
def warehouse():
    with Warehouse(DATA_DIR) as w:
        yield w


@pytest.fixture()
def data_dir() -> Path:
    return DATA_DIR
