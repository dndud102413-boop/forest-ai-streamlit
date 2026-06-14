"""end-to-end 파이프라인 (합성 데이터)."""
import pytest
from PIL import Image

from forest_reco.pipeline import analyze
from forest_reco.exif_gps import write_gps_exif


def test_analyze_by_coords(mock_sources):
    res = analyze(lat=37.95, lon=127.66, goal="탄소흡수", audience="시민",
                  sources=mock_sources, top_k=5)
    assert res["ok"]
    assert res["location"]["source"] == "manual"
    assert res["site"]["elevation_m"] is not None
    assert res["site"]["climate_zone"]
    assert 1 <= len(res["recommendations"]) <= 5
    # 점수 내림차순
    scores = [r["적합점수"] for r in res["recommendations"]]
    assert scores == sorted(scores, reverse=True)
    # 설명 항상 존재(오프라인 폴백 포함)
    assert res["explanation"]["text"]


def test_analyze_by_photo(mock_sources, tmp_path):
    plain = tmp_path / "p.jpg"
    Image.new("RGB", (32, 24), (10, 120, 10)).save(plain, "jpeg")
    geo = tmp_path / "geo.jpg"
    write_gps_exif(str(plain), 37.95, 127.66, str(geo))

    res = analyze(photo=str(geo), sources=mock_sources, top_k=3)
    assert res["ok"]
    assert res["location"]["source"] == "exif"
    assert res["location"]["lat"] == pytest.approx(37.95, abs=1e-3)


def test_analyze_no_location(mock_sources):
    res = analyze(sources=mock_sources)
    assert not res["ok"]
    assert "위치" in res["message"]


def test_analyze_out_of_range(mock_sources):
    # 합성 데이터 영역 밖 좌표 → 범위 밖 메시지
    res = analyze(lat=30.0, lon=122.0, sources=mock_sources)
    assert not res["ok"]


def test_point_in_polygon_fast_path(mock_sources):
    """영역 내부 좌표는 nearest 폴백이 아니라 contains(within) 빠른 경로로 잡혀야 한다.
    (sindex predicate 방향 버그 회귀 방지)"""
    res = analyze(lat=37.95, lon=127.66, sources=mock_sources, top_k=2, explain=False)
    assert res["forest_info"]["inside_polygon"] is True
    assert res["forest_info"]["distance_m"] == 0.0
    assert res["forest_nearest"] is False


def test_dem_edge_point_has_elevation(mock_sources):
    """DEM 가장자리 반-픽셀 띠의 점도 bilinear 클램프로 고도가 나와야(예외 탈락 방지)."""
    tq = mock_sources.terrain.query(127.5008, 37.6008, point_crs="EPSG:4326")
    assert tq.found
    assert tq.elevation_m is not None


def test_slope_finite_no_fake_cliff(mock_sources):
    """재투영 nodata 처리로 가짜 급경사(≈88°) 인공물이 없어야 한다."""
    tq = mock_sources.terrain.query(127.8, 37.85, point_crs="EPSG:4326")
    assert tq.found
    if tq.slope_deg is not None:
        assert 0.0 <= tq.slope_deg < 80.0


def test_explanation_offline_fallback(mock_sources):
    res = analyze(lat=37.95, lon=127.66, sources=mock_sources,
                  gemini_api_key=None, top_k=3)
    assert res["explanation"]["source"] == "fallback"
