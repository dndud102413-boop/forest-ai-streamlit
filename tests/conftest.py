import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from forest_reco.pipeline import DataSources


@pytest.fixture(scope="session")
def tmp_data_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("forest_data")


@pytest.fixture(scope="session")
def mock_sources(tmp_data_dir):
    """합성 임상도/DEM 기반 DataSources (세션 1회 생성)."""
    from forest_reco.config import Settings

    s = Settings()
    s.data_dir = tmp_data_dir
    src = DataSources(settings=s, use_mock=True)
    _ = src.forest
    _ = src.terrain
    _ = src.db
    return src
