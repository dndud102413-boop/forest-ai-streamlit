"""수종 추천/기후대 판정 로직."""
import pytest

from forest_reco.climate import classify_zone
from forest_reco.species_db import default_db, Species, SpeciesDB
from forest_reco.recommender import SiteContext, recommend, _elevation_fit


@pytest.fixture(scope="module")
def db():
    return default_db()


def test_db_loads(db):
    assert len(db) >= 25
    # 별칭 매칭
    assert db.match("낙엽송") is not None
    assert db.match("낙엽송").korean_name.startswith("일본잎갈나무")
    assert db.match("소나무") is not None


def test_climate_zone_by_latitude():
    # 저위도 저지대 → 난대
    z_south = classify_zone(34.3, 50)
    assert z_south.zone == "난대"
    # 중부 저지대 → 온대중부
    z_mid = classify_zone(37.3, 100)
    assert z_mid.zone in ("온대중부", "온대남부")
    # 고산 → 한대(아고산)
    z_alp = classify_zone(37.7, 1600)
    assert z_alp.zone == "한대(아고산)"


def test_elevation_pushes_zone_colder():
    low = classify_zone(37.5, 50).eff_lat
    high = classify_zone(37.5, 1000).eff_lat
    assert high > low  # 고도↑ → 유효위도↑(더 한랭)


def test_recommend_highland_prefers_cold_species(db):
    site = SiteContext(lat=37.8, lon=128.0, elevation_m=1300, slope_deg=15,
                       aspect_dir="북향")
    recs = recommend(site, db=db, top_k=8)
    assert recs
    names = [r.species.korean_name for r in recs]
    # 고지대 한랭 수종이 상위에 (난대 상록활엽수는 제외돼야)
    assert any(n in ("잣나무", "신갈나무", "자작나무", "분비나무", "전나무",
                     "거제수나무", "들메나무") for n in names[:4])
    assert "동백나무" not in names
    assert "후박나무" not in names


def test_recommend_lowland_warm(db):
    site = SiteContext(lat=34.5, lon=127.5, elevation_m=80, slope_deg=8,
                       aspect_dir="남향")
    recs = recommend(site, db=db, top_k=8)
    names = [r.species.korean_name for r in recs]
    # 난대 저지대 → 상록활엽/난대 수종 포함
    assert any("가시나무" in n or n in ("동백나무", "후박나무", "황칠나무", "편백", "곰솔(해송)")
               for n in names)


def test_empirical_evidence_boosts_score(db):
    base = SiteContext(lat=37.6, lon=127.9, elevation_m=400, slope_deg=10, aspect_dir="남향")
    recs0 = {r.species.korean_name: r.total_score for r in recommend(base, db=db, top_k=30)}

    boosted = SiteContext(lat=37.6, lon=127.9, elevation_m=400, slope_deg=10,
                          aspect_dir="남향", neighborhood={"소나무": 20})
    recs1 = {r.species.korean_name: r.total_score for r in recommend(boosted, db=db, top_k=30)}
    assert recs1["소나무"] > recs0["소나무"]


def test_goal_filtering_changes_ranking(db):
    site = SiteContext(lat=36.8, lon=127.8, elevation_m=300, slope_deg=10, aspect_dir="남향")
    carbon = recommend(site, db=db, goal="탄소흡수", top_k=5)
    timber = recommend(site, db=db, goal="용재생산", top_k=5)
    # 목적에 따라 상위 구성이 달라져야
    assert [r.species.korean_name for r in carbon] != [r.species.korean_name for r in timber]


def test_match_no_overmatch(db):
    """짧은/모호한 질의가 엉뚱한 단일 수종으로 오매칭되지 않아야(경험가점 오염 방지)."""
    assert db.match("나무") is None
    assert db.match("참나무") is None          # 그룹라벨은 단일종에 몰지 않음
    assert db.match("소나무류").korean_name == "소나무"   # 접미 '류'는 포함매칭
    assert db.match("리기다소나무").korean_name == "리기다소나무"
    assert db.match("낙엽송").korean_name.startswith("일본잎갈나무")


def test_elevation_fit_no_boundary_inversion():
    """적정범위 가장자리가 범위 바로 밖보다 낮아지는 역전이 없어야 한다."""
    sp = Species(korean_name="t", scientific_name="t", leaf_type="침엽수",
                 climate_zones=["온대중부"], elev_min_m=300, elev_max_m=1700)
    center = _elevation_fit(sp, 1000).score
    edge = _elevation_fit(sp, 1700).score
    just_out = _elevation_fit(sp, 1730).score
    far_out = _elevation_fit(sp, 2100).score
    assert center >= edge >= just_out >= far_out
    assert far_out == 0.0 or far_out < just_out


def test_empty_db_is_respected():
    """명시적으로 빈 DB를 넘기면 기본 DB로 대체되지 않고 빈 추천을 반환."""
    site = SiteContext(lat=37.5, lon=127.8, elevation_m=400, slope_deg=10, aspect_dir="남향")
    assert recommend(site, db=SpeciesDB([]), top_k=5) == []


def test_cautions_for_cold_sensitive_in_highland(db):
    site = SiteContext(lat=37.8, lon=128.0, elevation_m=1300, slope_deg=15, aspect_dir="북향")
    recs = recommend(site, db=db, top_k=40, include_unsuitable=True)
    camellia = next((r for r in recs if r.species.korean_name == "동백나무"), None)
    if camellia:  # 포함됐다면 반드시 경고가 있어야
        assert any("내한성" in c or "기후대" in c for c in camellia.cautions)
