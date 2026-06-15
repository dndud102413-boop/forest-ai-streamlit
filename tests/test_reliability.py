"""reliability.py 순수 계산 함수 단위테스트(실데이터 불필요)."""
from forest_reco.reliability import (
    sdm_probability_gap, neighbor_agreement, shannon_index,
    environment_diversity, overall_reliability,
    LEVEL_HIGH, LEVEL_MID, LEVEL_LOW, LEVEL_NA,
)


# 1) SDM 확률 차이 -----------------------------------------------------------
def test_prob_gap_high():
    r = sdm_probability_gap({"소나무": 0.62, "낙엽송": 0.34, "잣나무": 0.04})
    assert r["top1_species"] == "소나무"
    assert r["top2_species"] == "낙엽송"
    assert abs(r["gap"] - 0.28) < 1e-6
    assert r["level"] == LEVEL_HIGH


def test_prob_gap_low():
    r = sdm_probability_gap({"소나무": 0.40, "낙엽송": 0.36})
    assert r["level"] == LEVEL_LOW


def test_prob_gap_mid():
    r = sdm_probability_gap({"소나무": 0.50, "낙엽송": 0.35})
    assert r["level"] == LEVEL_MID


def test_prob_gap_empty_is_limited():
    assert sdm_probability_gap({})["level"] == LEVEL_NA


# 2) 주변 임분 일치도 --------------------------------------------------------
def test_neighbor_agreement_top3():
    shares = {"소나무": 0.42, "신갈나무": 0.20, "낙엽송": 0.18,
              "자작나무": 0.12, "굴참나무": 0.08}
    r = neighbor_agreement(shares, ["소나무", "낙엽송", "잣나무"], "소나무", 1000)
    # 소나무·낙엽송 2개가 주변 Top5에 포함 → 2/3
    assert abs(r["top3_agreement"] - round(2 / 3, 3)) < 1e-6
    assert abs(r["recommended_top1_share"] - 0.42) < 1e-6
    assert r["level"] == LEVEL_HIGH          # top1_share 0.42 ≥ 0.30


def test_neighbor_agreement_low():
    shares = {"신갈나무": 0.6, "굴참나무": 0.4}
    r = neighbor_agreement(shares, ["소나무", "낙엽송", "잣나무"], "소나무", 1000)
    assert r["top3_agreement"] == 0.0
    assert r["level"] == LEVEL_LOW


def test_neighbor_agreement_empty_is_limited():
    assert neighbor_agreement({}, ["소나무"], "소나무", 1000)["level"] == LEVEL_NA


# 3) Shannon + 환경 다양성 ---------------------------------------------------
def test_shannon_index_uniform_vs_single():
    # 단일 수종 → 0, 균등 4종 → ln(4)≈1.386
    assert shannon_index({"소나무": 1.0}) == 0.0
    even = shannon_index({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25})
    assert abs(even - 1.386) < 0.01


def test_environment_diversity_low():
    # 균질: 모든 지표 낮음 → 낮음(대표성 높음)
    r = environment_diversity(elevation_std=15, slope_std=3, species_shannon=0.5, radius_m=1000)
    assert r["level"] == LEVEL_LOW


def test_environment_diversity_high():
    r = environment_diversity(elevation_std=120, slope_std=14, species_shannon=1.6, radius_m=1000)
    assert r["level"] == LEVEL_HIGH


def test_environment_diversity_not_pure_and():
    # 한 지표만 높아도 AND가 아니라 점수평균이라 '낮음'으로 떨어지지 않음
    r = environment_diversity(elevation_std=120, slope_std=2, species_shannon=0.3, radius_m=1000)
    assert r["level"] in (LEVEL_LOW, LEVEL_MID)  # 평균 (2+0+0)/3≈0.67 → 보통 경계


def test_environment_diversity_empty_is_limited():
    assert environment_diversity(None, None, None, 1000)["level"] == LEVEL_NA


# 4) 종합 신뢰도 -------------------------------------------------------------
def test_overall_high():
    gap = {"level": LEVEL_HIGH}
    nb = {"level": LEVEL_HIGH}
    dv = {"level": LEVEL_LOW}      # 다양성 낮음 = 신뢰에 +
    assert overall_reliability(gap, nb, dv)["level"] == LEVEL_HIGH


def test_overall_low():
    gap = {"level": LEVEL_LOW}
    nb = {"level": LEVEL_LOW}
    dv = {"level": LEVEL_HIGH}     # 다양성 높음 = 신뢰에 -
    assert overall_reliability(gap, nb, dv)["level"] == LEVEL_LOW


def test_overall_all_limited_is_limited():
    na = {"level": LEVEL_NA}
    assert overall_reliability(na, na, na)["level"] == LEVEL_NA
