"""수종분포모델(SDM): 학습/예측 + 추천 블렌딩."""
import pytest

from forest_reco.species_db import default_db
from forest_reco.recommender import SiteContext, recommend


def test_recommend_blends_sdm_probs():
    """sdm_probs를 주면 해당 수종 점수가 오르고 데이터기반확률이 노출된다."""
    db = default_db()
    site = SiteContext(lat=37.8, lon=128.0, elevation_m=1300, slope_deg=15, aspect_dir="북향")
    base = {r.species.korean_name: r.total_score for r in recommend(site, db=db, top_k=40)}
    boosted = recommend(site, db=db, top_k=40, sdm_probs={"분비나무": 0.9, "잣나무": 0.3})
    bmap = {r.species.korean_name: r for r in boosted}
    assert bmap["분비나무"].total_score > base.get("분비나무", 0)
    assert bmap["분비나무"].sdm_prob == 0.9
    assert bmap["분비나무"].as_dict()["데이터기반확률"] == 0.9


def test_sdm_weight_scales_influence():
    """sdm_weight=0이면 SDM 확률을 줘도 점수 불변(신뢰도 비례 가중의 하한)."""
    db = default_db()
    site = SiteContext(lat=37.8, lon=128.0, elevation_m=1300, slope_deg=15, aspect_dir="북향")
    base = {r.species.korean_name: r.total_score for r in recommend(site, db=db, top_k=40)}
    w0 = {r.species.korean_name: r.total_score
          for r in recommend(site, db=db, top_k=40, sdm_probs={"분비나무": 0.9}, sdm_weight=0)}
    assert w0["분비나무"] == pytest.approx(base["분비나무"], abs=0.01)
    # 가중치를 주면 올라간다
    wfull = {r.species.korean_name: r.total_score
             for r in recommend(site, db=db, top_k=40, sdm_probs={"분비나무": 0.9}, sdm_weight=30)}
    assert wfull["분비나무"] > base["분비나무"]


def test_pipeline_reports_sdm_quality_and_weight(mock_sources):
    from forest_reco.pipeline import analyze
    r = analyze(lat=37.95, lon=127.66, sources=mock_sources, top_k=2, explain=False, use_sdm=True)
    assert r["sdm_used"] is True
    assert r["sdm_quality"] is not None
    assert 0 <= r["sdm_weight_applied"] <= 30   # 신뢰도 비례로 0~30 사이


@pytest.mark.slow
def test_sdm_ensemble_trains_and_predicts(mock_sources):
    """앙상블(hgb+rf) 학습·예측 — 확률 평균이 합=1 유지."""
    from forest_reco.sdm import SpeciesDistributionModel
    sdm = SpeciesDistributionModel.train(
        mock_sources.forest, mock_sources.terrain,
        n_samples=600, min_class=8, algos=("hgb", "rf"))
    assert sdm.algos == ["hgb", "rf"]
    assert sdm.report["algos"] == ["hgb", "rf"]
    res = sdm.predict(elevation=1300, slope=15, aspect_deg=10, lat=37.8)
    assert abs(sum(res.probs.values()) - 1.0) < 1e-6


@pytest.mark.slow
def test_sdm_train_and_predict(mock_sources):
    """합성 임상도로 SDM 학습 → 예측이 정상 동작(누수 없는 실관측 학습)."""
    from forest_reco.sdm import SpeciesDistributionModel

    sdm = SpeciesDistributionModel.train(
        mock_sources.forest, mock_sources.terrain, n_samples=600, min_class=8)
    assert sdm.report["n_classes"] >= 2
    assert 0.0 <= sdm.report["accuracy"] <= 1.0
    res = sdm.predict(elevation=1300, slope=15, aspect_deg=10, lat=37.8)
    assert abs(sum(res.probs.values()) - 1.0) < 1e-6   # 확률 합 = 1
    assert res.top[0][1] >= res.top[-1][1]
    # KB 매핑
    mapped = sdm.predict_for_site(
        SiteContext(lat=37.8, lon=128.0, elevation_m=1300, slope_deg=15,
                    aspect_dir="북향", aspect_deg=10),
        default_db())
    assert isinstance(mapped, dict) and mapped
