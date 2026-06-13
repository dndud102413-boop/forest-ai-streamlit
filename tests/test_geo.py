"""geo 모듈: 좌표계 변환, 래스터 셀 샘플링(경계검사/nodata), 경사/향."""
import math

import numpy as np
import pytest

from forest_reco.geo import (
    transform_point, sample_raster, compute_slope_aspect,
    aspect_to_direction, RasterSampleError, haversine_m,
)


def test_transform_point_identity():
    x, y = transform_point(127.7, 37.8, "EPSG:4326", "EPSG:4326")
    assert (x, y) == (127.7, 37.8)


def test_transform_wgs84_to_5179_roundtrip():
    x, y = transform_point(127.7298, 37.8813, "EPSG:4326", "EPSG:5179")
    # 5179 좌표는 백만 단위
    assert 900_000 < x < 1_100_000
    lon, lat = transform_point(x, y, "EPSG:5179", "EPSG:4326")
    assert lon == pytest.approx(127.7298, abs=1e-4)
    assert lat == pytest.approx(37.8813, abs=1e-4)


def test_aspect_to_direction():
    assert aspect_to_direction(0) == "북향"
    assert aspect_to_direction(90) == "동향"
    assert aspect_to_direction(180) == "남향"
    assert aspect_to_direction(270) == "서향"
    assert aspect_to_direction(float("nan")) == "평지"
    assert aspect_to_direction(-1) == "평지"


def test_compute_slope_aspect_flat():
    flat = np.full((10, 10), 100.0)
    slope, aspect = compute_slope_aspect(flat, 30.0, 30.0)
    assert np.allclose(slope, 0.0)


def test_compute_slope_known_grade():
    # x방향으로 30m마다 30m 상승 → 경사 45도
    arr = np.tile(np.arange(10) * 30.0, (10, 1))
    slope, aspect = compute_slope_aspect(arr, 30.0, 30.0)
    assert slope[5, 5] == pytest.approx(45.0, abs=1.0)


class _FakeDS:
    """rasterio DatasetReader 최소 모킹."""
    def __init__(self, arr, transform, crs="EPSG:4326", nodata=None):
        self._arr = arr
        self.transform = transform
        self.crs = crs
        self.nodata = nodata
        self.height, self.width = arr.shape
        from rasterio.transform import array_bounds
        self.bounds = array_bounds(self.height, self.width, transform)

    def index(self, x, y):
        from rasterio.transform import rowcol
        return rowcol(self.transform, x, y)

    def read(self, band):
        return self._arr


def _make_ds(nodata=None):
    from rasterio.transform import from_origin
    arr = np.arange(100, dtype="float64").reshape(10, 10)
    # 좌상단(0,0) 원점, 셀 1도
    return _FakeDS(arr, from_origin(0.0, 10.0, 1.0, 1.0), nodata=nodata)


def test_sample_raster_in_bounds():
    ds = _make_ds()
    v = sample_raster(ds, 0.5, 9.5, point_crs="EPSG:4326", method="nearest")
    assert v == 0.0  # 좌상단 셀


def test_sample_raster_out_of_bounds_raises():
    ds = _make_ds()
    with pytest.raises(RasterSampleError):
        sample_raster(ds, 999.0, 999.0, point_crs="EPSG:4326")
    # 음수 인덱스 silent-wrap 방지 (경계 바로 밖)
    with pytest.raises(RasterSampleError):
        sample_raster(ds, -0.5, 5.0, point_crs="EPSG:4326")


def test_sample_raster_nodata_raises():
    ds = _make_ds(nodata=0.0)
    with pytest.raises(RasterSampleError):
        sample_raster(ds, 0.5, 9.5, point_crs="EPSG:4326")  # 값 0 == nodata


def test_haversine():
    d = haversine_m(127.0, 37.0, 127.0, 37.01)
    assert 1100 < d < 1200  # 위도 0.01도 ≈ 1.11km
