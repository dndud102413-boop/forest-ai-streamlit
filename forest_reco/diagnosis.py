"""
diagnosis.py — 현재 숲(기존 임분) 진단 (투명한 규칙 엔진, ML 아님)

원본 노트북의 make_growth_suitability / make_pest_vulnerability /
make_management_priority 규칙을 **정리해서 되살린** 것이다.

중요: 원본의 문제는 '규칙'이 아니라 '규칙이 만든 답을 같은 입력으로 ML에 다시
학습시킨 것'이었다(순환 학습). 규칙 자체는 투명한 진단 도구로 충분히 유용하므로,
ML 없이 규칙만 그대로 사용한다. (추천 기능과는 별개의 보조 기능)

  - 생육 적합도: 현재 임분이 얼마나 잘 자랄 환경인가
  - 병해충 취약도: 재선충·시들음병 등에 얼마나 취약한가
  - 관리 우선순위: 위 둘을 합쳐 관리가 시급한 정도

※ 임계값은 현장 경험 기반의 휴리스틱이며, 실제 운용 전 전문가 보정 권장.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


def _age_num(agcls) -> Optional[int]:
    """'3영급'/'Ⅲ'/'3' → 정수 영급. 파싱 실패 시 None. (부분문자열 매칭 금지)"""
    if agcls is None:
        return None
    s = str(agcls)
    m = re.search(r"\d+", s)
    if m:
        return int(m.group())
    roman = {"Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4, "Ⅴ": 5, "Ⅵ": 6,
             "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}
    for k, v in roman.items():
        if k in s:
            return v
    return None


@dataclass
class StandDiagnosis:
    growth_suitability: str          # 생육 적합도: 높음/보통/낮음
    pest_vulnerability: str          # 병해충 취약도: 높음/보통/낮음
    management_priority: str         # 관리 우선순위: 매우 높음/높음/보통/낮음
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "생육_적합도": self.growth_suitability,
            "병해충_취약도": self.pest_vulnerability,
            "관리_우선순위": self.management_priority,
            "근거": self.reasons,
        }


def _growth_suitability(species, age, dmcls, dnst, elev, slope, aspect_dir):
    score, why = 0, []
    s = str(species or "")
    if "소나무" in s or "잣나무" in s:
        score += 2
    else:
        score += 1
    if age in (3, 4):
        score += 2; why.append("생육 왕성 영급(3~4)")
    elif age == 5:
        score += 1
    if dmcls and "중경" in str(dmcls):
        score += 2
    elif dmcls and "대경" in str(dmcls):
        score += 1
    if dnst and str(dnst) == "중":
        score += 2
    elif dnst and str(dnst) == "밀":
        score += 1
    if elev is not None and 100 <= elev <= 700:
        score += 2; why.append("생육 적정 고도대")
    elif elev is not None and elev < 1000:
        score += 1
    if slope is not None and slope <= 15:
        score += 2
    elif slope is not None and slope <= 30:
        score += 1
    if aspect_dir in ("남향", "남동향", "동향"):
        score += 1; why.append("일조 양호한 향")
    level = "높음" if score >= 10 else "보통" if score >= 6 else "낮음"
    return level, why


def _pest_vulnerability(species, age, dmcls, dnst, elev, slope, aspect_dir):
    score, why = 0, []
    s = str(species or "")
    if "소나무" in s:
        score += 2; why.append("소나무류(재선충 위험)")
    elif "잣나무" in s:
        score += 1
    if "참나무" in s or "신갈" in s or "굴참" in s or "졸참" in s or "상수리" in s:
        why.append("참나무류(시들음병 주의)")
        score += 1
    if age in (5, 6):
        score += 2; why.append("노령 임분")
    elif age == 4:
        score += 1
    if dmcls and "대경" in str(dmcls):
        score += 2
    elif dmcls and "중경" in str(dmcls):
        score += 1
    if dnst and str(dnst) == "밀":
        score += 2; why.append("과밀(병해충 확산 용이)")
    elif dnst and str(dnst) == "중":
        score += 1
    if elev is not None and elev <= 700:
        score += 1
    if slope is not None and slope >= 30:
        score += 1
    if aspect_dir in ("남향", "남서향", "서향"):
        score += 1
    level = "높음" if score >= 8 else "보통" if score >= 5 else "낮음"
    return level, why


def _management_priority(growth: str, pest: str) -> str:
    table = {
        ("낮음", "높음"): "매우 높음",
        ("보통", "높음"): "높음",
        ("낮음", "보통"): "높음",
        ("높음", "높음"): "보통",
        ("보통", "보통"): "보통",
        ("낮음", "낮음"): "보통",
    }
    return table.get((growth, pest), "낮음")


def diagnose_stand(forest_info: Optional[dict], terrain: Optional[dict]) -> Optional[StandDiagnosis]:
    """
    현재 임분 진단. forest_info(임상도 속성)와 terrain(지형)을 받아 규칙으로 평가.
    forest_info가 없으면(범위 밖) None.
    """
    if not forest_info:
        return None
    species = forest_info.get("수종")
    age = _age_num(forest_info.get("영급"))
    dmcls = forest_info.get("경급")
    dnst = forest_info.get("밀도")
    terrain = terrain or {}
    elev = terrain.get("고도")
    slope = terrain.get("경사")
    aspect_dir = terrain.get("향", "평지")

    growth, g_why = _growth_suitability(species, age, dmcls, dnst, elev, slope, aspect_dir)
    pest, p_why = _pest_vulnerability(species, age, dmcls, dnst, elev, slope, aspect_dir)
    priority = _management_priority(growth, pest)

    reasons = []
    reasons += [f"생육: {w}" for w in g_why]
    reasons += [f"병해충: {w}" for w in p_why]
    return StandDiagnosis(growth, pest, priority, reasons)
