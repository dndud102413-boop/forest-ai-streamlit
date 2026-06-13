"""EXIF GPS 추출: 부호처리, 누락, 라운드트립."""
import pytest
from PIL import Image

from forest_reco.exif_gps import extract_gps, write_gps_exif


@pytest.fixture
def plain_jpg(tmp_path):
    p = tmp_path / "plain.jpg"
    Image.new("RGB", (32, 24), (10, 120, 10)).save(p, "jpeg")
    return p


def test_no_gps_returns_not_ok(plain_jpg):
    g = extract_gps(str(plain_jpg))
    assert not g.ok
    assert g.lat is None and g.lon is None
    assert g.reason


@pytest.mark.parametrize("lat,lon", [
    (37.8813, 127.7298),    # 춘천 (N, E)
    (-33.8688, 151.2093),   # 시드니 (S, E) — 음수 위도
    (51.5074, -0.1278),     # 런던 (N, W) — 음수 경도
])
def test_gps_roundtrip_sign(plain_jpg, tmp_path, lat, lon):
    dst = tmp_path / "geo.jpg"
    write_gps_exif(str(plain_jpg), lat, lon, str(dst))
    g = extract_gps(str(dst))
    assert g.ok
    assert g.lat == pytest.approx(lat, abs=1e-3)
    assert g.lon == pytest.approx(lon, abs=1e-3)


def test_extract_from_bytes(plain_jpg, tmp_path):
    dst = tmp_path / "geo.jpg"
    write_gps_exif(str(plain_jpg), 37.5, 127.5, str(dst))
    g = extract_gps(dst.read_bytes())
    assert g.ok and g.source == "exif"
