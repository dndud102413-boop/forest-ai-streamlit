"""실데이터 견고성 회귀 테스트 (재진단 7건)."""
import numpy as np
import pytest

from forest_reco.species_db import default_db
from forest_reco.recommender import SiteContext, recommend
from forest_reco.geo import compute_slope_aspect, aspect_to_direction


@pytest.fixture(scope="module")
def db():
    return default_db()


# --- #2/#6: KOFTR 그룹라벨·학명 매칭 ---
def test_scientific_name_matches(db):
    assert db.match("Pinus densiflora").korean_name == "소나무"


def test_group_label_fans_out(db):
    oaks = db.match_all("참나무류")
    assert len(oaks) >= 3
    assert all(s.genus == "Quercus" or s.korean_name.endswith("참나무") for s in oaks)
    conif = db.match_all("기타침엽수")
    assert conif and all(s.leaf_type == "침엽수" for s in conif)
    assert db.match_all("없는수종xyz") == []


def test_neighborhood_group_label_gives_empirical_signal(db):
    """그룹라벨('참나무류')도 경험가점에 반영돼야(무음 탈락 방지)."""
    site = SiteContext(lat=37.6, lon=127.9, elevation_m=500, slope_deg=10,
                       aspect_dir="남향", neighborhood={"참나무류": 30})
    recs = recommend(site, db=db, top_k=40)
    boosted = [r for r in recs if r.empirical_count > 0]
    assert boosted, "그룹라벨이 어떤 수종에도 경험가점을 주지 못함"
    assert all(r.species.genus == "Quercus" or r.species.korean_name.endswith("참나무")
               for r in boosted)


# --- #4: 평지가 '북향'으로 잘못 인코딩되지 않아야 ---
def test_flat_terrain_has_no_aspect():
    flat = np.full((6, 6), 100.0)
    slope, aspect = compute_slope_aspect(flat, 30.0, 30.0)
    assert np.all(np.isnan(aspect))            # 평지는 향이 NaN
    assert aspect_to_direction(aspect[3, 3]) == "평지"


# --- #5: 토양 배수 요인 확장성(새 입력 레이어 = 요인 1개 추가) ---
def test_drainage_factor_activates_when_soil_given(db):
    site = SiteContext(lat=37.6, lon=127.9, elevation_m=400, slope_deg=10,
                       aspect_dir="남향", soil_drainage="양호")
    recs = recommend(site, db=db, top_k=3)
    assert any(f.name == "배수" for f in recs[0].factors)
    # 배수 정보 없으면 배수 요인 미포함(기존 동작 보존)
    site2 = SiteContext(lat=37.6, lon=127.9, elevation_m=400, slope_deg=10, aspect_dir="남향")
    recs2 = recommend(site2, db=db, top_k=3)
    assert not any(f.name == "배수" for f in recs2[0].factors)


# --- #1: 좌표계 무음 오라벨 차단 ---
def test_crs_sanity_check_rejects_mislabeled_5181():
    import geopandas as gpd
    from shapely.geometry import box
    from forest_reco.forest_map import ForestMap

    # 중부원점(5181) 범위(~28만, 44만) 좌표인데 .prj 없음 → 5179 가정 시 불일치 에러
    g = gpd.GeoDataFrame(
        {"FRTP_NM": ["침엽수림"], "KOFTR_NM": ["소나무"], "DMCLS_NM": ["중경목"],
         "AGCLS_NM": ["3영급"], "DNST_NM": ["중"]},
        geometry=[box(280000, 440000, 281000, 441000)], crs=None,
    )
    with pytest.warns(UserWarning):
        with pytest.raises(ValueError):
            ForestMap(g)
