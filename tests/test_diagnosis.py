"""현재 숲 진단(규칙 엔진) 테스트."""
import pytest

from forest_reco.diagnosis import diagnose_stand, _age_num


@pytest.mark.parametrize("val,exp", [
    ("3영급", 3), ("Ⅴ", 5), ("6", 6), ("13영급", 13), (None, None), ("기타", None),
])
def test_age_parsing_no_substring_bug(val, exp):
    assert _age_num(val) == exp


def test_diagnose_returns_valid_levels():
    forest = {"임종": "침엽수림", "수종": "소나무", "경급": "대경목",
              "영급": "6영급", "밀도": "밀"}
    terrain = {"고도": 500, "경사": 35, "향": "남향"}
    d = diagnose_stand(forest, terrain)
    assert d.growth_suitability in ("높음", "보통", "낮음")
    assert d.pest_vulnerability in ("높음", "보통", "낮음")
    assert d.management_priority in ("매우 높음", "높음", "보통", "낮음")
    # 노령 대경 과밀 소나무 남사면 → 병해충 취약도 높음 쪽
    assert d.pest_vulnerability == "높음"


def test_diagnose_none_when_no_forest():
    assert diagnose_stand(None, {"고도": 500}) is None


def test_pipeline_includes_diagnosis(mock_sources):
    from forest_reco.pipeline import analyze
    res = analyze(lat=37.95, lon=127.66, sources=mock_sources, top_k=2, explain=False)
    assert res["diagnosis"] is not None
    assert "관리_우선순위" in res["diagnosis"]
