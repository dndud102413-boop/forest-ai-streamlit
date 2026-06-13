"""
species_db.py — 적지적수(right tree, right site) 수종 지식베이스

원본 노트북의 "AI 모델"은 사람이 손으로 만든 규칙으로 라벨을 만든 뒤 그 라벨을
RandomForest/XGBoost로 다시 학습하는 **순환 학습**이었다. 모델은 규칙을 그대로
외울 뿐이라 정확도는 100%에 가깝지만 새로운 지식을 학습한 것이 아니다.
또한 노트북은 "기존 임분 진단"만 했고, 개발자의 실제 목표인 "식재 적합 수종
추천"은 구현돼 있지 않았다.

본 모듈은 그 두 문제를 모두 해결한다. 식재 추천은 본질적으로 *지식 기반 적합도
판정*(적지적수)이 정확하고 설명 가능하므로, 한국 산림청 적지적수 지식을 구조화한
KB를 둔다. 여기에 recommender.py가 "임상도 인접 임분에서 실제로 잘 자라는 수종"
이라는 경험적 신호를 결합(하이브리드)한다.

데이터는 forest_reco/data/species_db.json 에 분리(편집 가능)되어 있다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_DEFAULT_JSON = Path(__file__).resolve().parent / "data" / "species_db.json"

# KOFTR_NM(임상도 수종명) ↔ KB 수종명 별칭. 임상도는 '낙엽송','해송' 등으로 표기됨.
_ALIASES = {
    "낙엽송": "일본잎갈나무(낙엽송)",
    "일본잎갈나무": "일본잎갈나무(낙엽송)",
    "해송": "곰솔(해송)",
    "엄나무": "음나무(엄나무)",
    "튤립나무": "백합나무(튤립나무)",
    "강원지방소나무": "소나무",
    "중부지방소나무": "소나무",
}


@dataclass
class Species:
    korean_name: str
    scientific_name: str
    leaf_type: str                      # 침엽수 / 낙엽활엽수 / 상록활엽수
    climate_zones: list[str]
    elev_min_m: float
    elev_max_m: float
    slope_pref: str = "전지형"
    aspect_pref: list[str] = field(default_factory=lambda: ["무관"])
    drainage: str = "무관"
    drought_tolerance: str = "중"
    cold_hardiness: str = "중"
    growth_rate: str = "중간"
    carbon_seq: str = "중"
    purposes: list[str] = field(default_factory=list)
    pest_notes: str = ""
    notes: str = ""

    # ---- 파생 ----
    @property
    def name_tokens(self) -> list[str]:
        """매칭용 이름 토큰: 본명 + 괄호 안/밖 분리 + 학명(전체)."""
        toks = {self.korean_name}
        m = re.match(r"(.+?)\((.+?)\)", self.korean_name)
        if m:
            toks.add(m.group(1).strip())
            toks.add(m.group(2).strip())
        if self.scientific_name:
            # 학명 병기(KOFTR_NM='Pinus densiflora' 등) 정확일치용. 속명 단독은
            # 오매칭 위험이 있어 넣지 않는다(속명 팬아웃은 match_all에서 처리).
            toks.add(self.scientific_name.strip())
        return [t for t in toks if t]

    @property
    def genus(self) -> str:
        return self.scientific_name.split()[0] if self.scientific_name else ""

    @property
    def forest_type(self) -> str:
        """임상도 임종(FRTP)과 대응되는 임상 구분."""
        return "침엽수림" if self.leaf_type == "침엽수" else "활엽수림"


class SpeciesDB:
    def __init__(self, species: list[Species], sourcing_notes: str = ""):
        self.species = species
        self.sourcing_notes = sourcing_notes
        self._by_token: dict[str, Species] = {}
        for sp in species:
            for t in sp.name_tokens:
                self._by_token.setdefault(t, sp)

    def __len__(self) -> int:
        return len(self.species)

    def __iter__(self):
        return iter(self.species)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "SpeciesDB":
        path = Path(path or _DEFAULT_JSON)
        raw = json.loads(path.read_text(encoding="utf-8"))
        sp_list = [Species(**_filter_fields(s)) for s in raw["species"]]
        return cls(sp_list, sourcing_notes=raw.get("sourcing_notes", ""))

    def match(self, koftr_name: str) -> Optional[Species]:
        """임상도 KOFTR_NM 문자열을 KB 수종으로 매칭(별칭/부분일치)."""
        if not koftr_name:
            return None
        name = str(koftr_name).strip()
        if name in self._by_token:
            return self._by_token[name]
        if name in _ALIASES and _ALIASES[name] in self._by_token:
            # alias가 정식명일 수도, 토큰일 수도 있음
            target = _ALIASES[name]
            return self._by_token.get(target) or next(
                (s for s in self.species if s.korean_name == target), None
            )
        # 부분일치: 질의가 토큰을 '포함'하는 경우만 허용(예 '소나무류' ⊃ '소나무').
        # 양방향(name in tok)은 '나무'·'참나무' 같은 짧은/모호한 질의가 삽입순서대로
        # 엉뚱한 단일 수종에 매칭돼 경험가점을 오염시키므로 제거한다.
        # 후보가 여러 개면 가장 긴(가장 구체적) 토큰을 결정적으로 선택, 없으면 None.
        candidates = [(tok, sp) for tok, sp in self._by_token.items() if tok and tok in name]
        if candidates:
            _, sp = max(candidates, key=lambda kv: len(kv[0]))
            return sp
        return None

    def match_all(self, koftr_name: str) -> list[Species]:
        """
        임상도 KOFTR_NM을 KB 수종 '집합'으로 매핑. 단일종이면 [그 종],
        그룹라벨('참나무류','기타활엽수','기타침엽수')이면 멤버 전체, 실패 시 [].

        경험적 빈도/SDM 신호를 단일종에 몰아주는 왜곡을 피하고, 그룹라벨이 무음
        탈락하지 않도록 여러 종에 분배(fan-out)한다. (recommender가 사용)
        """
        if not koftr_name:
            return []
        sp = self.match(koftr_name)
        if sp is not None:
            return [sp]
        name = str(koftr_name).strip()
        if "참나무" in name:   # '참나무류' 등
            return [s for s in self.species
                    if s.korean_name.endswith("참나무") or s.genus == "Quercus"]
        if name in ("기타침엽수", "침엽수"):
            return [s for s in self.species if s.leaf_type == "침엽수"]
        if name in ("기타활엽수", "활엽수"):
            return [s for s in self.species if "활엽수" in s.leaf_type]
        return []


# Species 데이터클래스에 없는 잉여 키(예: 향후 추가 필드)는 무시
_ALLOWED = set(Species.__dataclass_fields__.keys())


def _filter_fields(d: dict) -> dict:
    return {k: v for k, v in d.items() if k in _ALLOWED}


# 편의 싱글턴
def default_db() -> SpeciesDB:
    return SpeciesDB.load()
