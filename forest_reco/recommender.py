"""
recommender.py — 위치 기반 식재 적합 수종 추천(하이브리드)

개발자의 실제 목표: "사진의 위경도 위치에 *심을 수 있는 적합한 수종*을 추천."

접근(설명 가능 + 경험적 근거 결합):
  (A) 지식 기반 적지적수 점수 — species_db의 기후대/고도/경사/향/배수/목적 요구를
      현장 입지와 대조한 적합도(0~1).
  (B) 경험적 근거 — 임상도 인접 임분에서 실제로 우점하는 수종일수록 가점
      (그 환경에서 "실제로 잘 자라고 있다"는 강력한 증거).
  최종점수 = 가중합 → 0~100 정규화, 요인별 설명 동봉.

블랙박스 ML(더구나 순환학습)보다 투명하고, 다양한 타겟층(시민/산주/공무원/연구자)
모두에게 "왜 이 수종인가"를 근거와 함께 제시할 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .climate import classify_zone, zone_distance, ClimateZone
from .species_db import Species, SpeciesDB, default_db

# 식재 목적 → species.purposes 매핑(사용자 선택)
GOALS = {
    "탄소흡수": "탄소흡수",
    "용재생산": "용재",
    "경관조경": "조경경관",
    "사방방재": "사방방재",
    "생물다양성": "생물다양성",
    "특용수": "특용(열매/수액)",
    "밀원": "밀원(꿀)",
    "도시녹화": "내공해도시",
}

# 적합도 가중치(경험가점은 별도 가산). 코어 5요인 합 = 1.0.
# 새 입력 레이어(토양/기후격자 등)를 추가하면 여기에 가중치를 더하고,
# recommend()가 활성 요인의 가중치 합으로 자동 정규화한다(확장성).
WEIGHTS = {
    "climate": 0.34,
    "elevation": 0.30,
    "slope": 0.12,
    "aspect": 0.10,
    "purpose": 0.14,
    "drainage": 0.12,   # 토양 배수 정보가 있을 때만 활성(SiteContext.soil_drainage)
}
EMPIRICAL_WEIGHT = 20        # 100점 중 경험적 근거(인접 임분 점유) 배점
SDM_WEIGHT = 30              # SDM(데이터기반 ML) 최대 배점. 호출부가 모델 신뢰도로 축소

_TOL = {"상": 1.0, "중": 0.6, "하": 0.3}
_ELEV_EDGE = 0.82      # 적정 고도범위 가장자리 점수(중심 1.0 → 가장자리 0.82)
_ELEV_BUF = 300.0      # 범위 밖 감쇠 거리(m)


@dataclass
class SiteContext:
    """추천에 필요한 현장 입지 맥락."""
    lat: float
    lon: float
    elevation_m: Optional[float] = None
    slope_deg: Optional[float] = None
    aspect_dir: str = "평지"
    aspect_deg: Optional[float] = None      # SDM 등 수치 입력용(향 원시값)
    soil_drainage: Optional[str] = None     # 토양 배수(양호/보통/습윤) — 있으면 배수 요인 활성
    climate: Optional[ClimateZone] = None
    # 임상도 인접 수종 빈도 {수종명: 개수}
    neighborhood: dict = field(default_factory=dict)
    # 현재 위치 임분 임종(침엽수림/활엽수림/혼효림) — 참고
    existing_forest_type: Optional[str] = None

    def ensure_climate(self) -> ClimateZone:
        if self.climate is None:
            self.climate = classify_zone(self.lat, self.elevation_m or 0.0)
        return self.climate


@dataclass
class FactorScore:
    name: str
    score: float        # 0~1
    weight: float
    reason: str


@dataclass
class Recommendation:
    species: Species
    total_score: float          # 0~100
    factors: list[FactorScore]
    empirical_count: int
    cautions: list[str]
    sdm_prob: float = 0.0       # SDM 예측 확률(제공 시)

    def as_dict(self) -> dict:
        d = {
            "수종": self.species.korean_name,
            "학명": self.species.scientific_name,
            "유형": self.species.leaf_type,
            "적합점수": round(self.total_score, 1),
            "점수세부": [
                {
                    "항목": f.name,
                    "점수": round(float(f.score), 3),
                    "가중치": round(float(f.weight), 3),
                    "근거": f.reason,
                }
                for f in self.factors
            ],
            "주요근거": [f"{f.name}: {f.reason}" for f in self.factors if f.score >= 0.6],
            "유의사항": self.cautions,
            "용도": self.species.purposes,
            "탄소흡수": self.species.carbon_seq,
            "인접임분근거수": self.empirical_count,
        }
        if self.sdm_prob:
            d["데이터기반확률"] = round(self.sdm_prob, 3)
        return d


# ---------------------------------------------------------------------------
# 개별 적합도 요인
# ---------------------------------------------------------------------------
def _climate_fit(sp: Species, zone: str) -> FactorScore:
    if zone in sp.climate_zones:
        return FactorScore("기후대", 1.0, WEIGHTS["climate"], f"{zone} 적지")
    # 인접 기후대면 부분 점수
    dmin = min((zone_distance(zone, z) for z in sp.climate_zones), default=99)
    if dmin == 1:
        return FactorScore("기후대", 0.45, WEIGHTS["climate"], f"{zone} 경계(인접대 분포)")
    return FactorScore("기후대", 0.0, WEIGHTS["climate"], f"{zone} 부적합(분포대 {sp.climate_zones})")


def _elevation_fit(sp: Species, elev: Optional[float]) -> FactorScore:
    if elev is None:
        return FactorScore("고도", 0.6, WEIGHTS["elevation"], "고도 정보 없음(중립)")
    lo, hi = sp.elev_min_m, sp.elev_max_m
    if lo <= elev <= hi:
        # 적정범위 안에서도 중심에 가까울수록 높게(중심 1.0 → 가장자리 _ELEV_EDGE)
        center = (lo + hi) / 2.0
        half = max(1.0, (hi - lo) / 2.0)
        rel = abs(elev - center) / half          # 0(중심)~1(가장자리)
        s = 1.0 - (1.0 - _ELEV_EDGE) * rel
        return FactorScore("고도", s, WEIGHTS["elevation"], f"{elev:.0f}m ∈ 적정 {lo:.0f}~{hi:.0f}m")
    # 범위 밖: 가장자리값(_ELEV_EDGE)에서 연속으로 감쇠(경계 역전 방지)
    if elev < lo:
        d = lo - elev
        s = max(0.0, _ELEV_EDGE * (1 - d / _ELEV_BUF))
        return FactorScore("고도", s, WEIGHTS["elevation"], f"{elev:.0f}m < 하한 {lo:.0f}m({d:.0f}m 미달)")
    d = elev - hi
    s = max(0.0, _ELEV_EDGE * (1 - d / _ELEV_BUF))
    return FactorScore("고도", s, WEIGHTS["elevation"], f"{elev:.0f}m > 상한 {hi:.0f}m({d:.0f}m 초과)")


def _slope_fit(sp: Species, slope: Optional[float]) -> FactorScore:
    if slope is None or sp.slope_pref in ("전지형", "급경사무관"):
        return FactorScore("경사", 0.8, WEIGHTS["slope"], f"경사 제약 적음({sp.slope_pref})")
    if sp.slope_pref == "완경사":
        if slope <= 15:
            return FactorScore("경사", 1.0, WEIGHTS["slope"], f"{slope:.0f}° 완경사 적합")
        if slope <= 30:
            return FactorScore("경사", 0.6, WEIGHTS["slope"], f"{slope:.0f}° 다소 급함")
        return FactorScore("경사", 0.3, WEIGHTS["slope"], f"{slope:.0f}° 급경사 부담")
    if sp.slope_pref == "중경사":
        if slope <= 30:
            return FactorScore("경사", 1.0, WEIGHTS["slope"], f"{slope:.0f}° 적합")
        return FactorScore("경사", 0.5, WEIGHTS["slope"], f"{slope:.0f}° 급경사")
    return FactorScore("경사", 0.8, WEIGHTS["slope"], f"{slope:.0f}°")


_ADJ = {
    "남향": {"남동향", "남서향"}, "북향": {"북동향", "북서향"},
    "동향": {"남동향", "북동향"}, "서향": {"남서향", "북서향"},
}


def _aspect_fit(sp: Species, aspect_dir: str) -> FactorScore:
    prefs = set(sp.aspect_pref)
    if "무관" in prefs or aspect_dir in ("평지", ""):
        return FactorScore("향", 0.85, WEIGHTS["aspect"], "향 제약 적음")
    if aspect_dir in prefs:
        return FactorScore("향", 1.0, WEIGHTS["aspect"], f"{aspect_dir} 선호")
    # 인접 방위면 부분 점수
    if any(aspect_dir in _ADJ.get(p, set()) or p in _ADJ.get(aspect_dir, set()) for p in prefs):
        return FactorScore("향", 0.7, WEIGHTS["aspect"], f"{aspect_dir}(선호향 인접)")
    return FactorScore("향", 0.5, WEIGHTS["aspect"], f"{aspect_dir}(선호 {sp.aspect_pref}와 상이)")


def _purpose_fit(sp: Species, goal: Optional[str]) -> FactorScore:
    if not goal:
        return FactorScore("목적", 1.0, WEIGHTS["purpose"], "목적 미지정(중립)")
    target = GOALS.get(goal, goal)
    if target in sp.purposes:
        return FactorScore("목적", 1.0, WEIGHTS["purpose"], f"'{goal}' 부합")
    return FactorScore("목적", 0.35, WEIGHTS["purpose"], f"'{goal}' 주 용도 아님")


def _drainage_fit(sp: Species, site_drainage: Optional[str]) -> FactorScore:
    """토양 배수 적합도. (확장 예시: 새 입력 레이어 = 요인함수 1개 추가)"""
    if not site_drainage or sp.drainage == "무관":
        return FactorScore("배수", 0.8, WEIGHTS["drainage"], "배수 제약 적음")
    if sp.drainage == site_drainage:
        return FactorScore("배수", 1.0, WEIGHTS["drainage"], f"{site_drainage} 적합")
    return FactorScore("배수", 0.5, WEIGHTS["drainage"], f"{site_drainage}(선호 {sp.drainage}와 상이)")


def _cautions(sp: Species, site: SiteContext) -> list[str]:
    out = []
    z = site.ensure_climate().zone
    if z not in sp.climate_zones:
        out.append(f"기후대({z})가 분포 적지가 아님 — 식재 신중")
    if site.elevation_m is not None:
        if site.elevation_m > sp.elev_max_m:
            out.append(f"고도 상한({sp.elev_max_m:.0f}m) 초과")
        if site.elevation_m < sp.elev_min_m:
            out.append(f"고도 하한({sp.elev_min_m:.0f}m) 미달")
    if sp.cold_hardiness == "하" and z in ("온대중부", "온대북부", "한대(아고산)"):
        out.append("내한성 약함 — 동해(겨울추위) 피해 우려")
    if sp.drought_tolerance == "하" and (site.slope_deg or 0) > 25 and site.aspect_dir in ("남향", "남서향", "서향"):
        out.append("내건성 약함 + 건조 사면 — 활착 불리")
    if sp.pest_notes:
        out.append(f"병해충 유의: {sp.pest_notes}")
    return out


# ---------------------------------------------------------------------------
# 추천 엔진
# ---------------------------------------------------------------------------
def recommend(
    site: SiteContext,
    db: Optional[SpeciesDB] = None,
    goal: Optional[str] = None,
    top_k: int = 8,
    include_unsuitable: bool = False,
    sdm_probs: Optional[dict] = None,
    sdm_weight: float = SDM_WEIGHT,
) -> list[Recommendation]:
    # 주의: SpeciesDB는 __len__을 구현하므로 'db or default_db()'는 빈 DB를 falsy로
    # 보고 기본 DB로 갈아끼운다. 명시적 None 검사로 호출자의 빈/부분집합 DB를 존중한다.
    db = default_db() if db is None else db
    zone = site.ensure_climate().zone

    # 경험적 빈도: 인접 수종명 → KB 수종 매칭하여 카운트 합산.
    # match_all로 그룹라벨('참나무류','기타활엽수')도 멤버에 분배(균등)하고,
    # total_emp는 미매칭 포함 전체로 두어 미매칭이 분모에 남아 분율을 희석한다.
    emp_counts: dict[str, float] = {}
    total_emp = 0
    unmatched = 0
    for koftr, cnt in (site.neighborhood or {}).items():
        cnt = int(cnt)
        total_emp += cnt
        members = db.match_all(koftr)
        if not members:
            unmatched += cnt
            continue
        share = cnt / len(members)
        for sp in members:
            emp_counts[sp.korean_name] = emp_counts.get(sp.korean_name, 0.0) + share

    # SDM 확률 정규화(최댓값 1.0 기준). sdm_weight는 호출부가 모델 신뢰도(f1 등)에
    # 비례해 줄여 넘길 수 있다(약한 모델은 적게, 강한 모델은 크게 반영 → 안전).
    sdm_probs = sdm_probs or {}
    sdm_max = max(sdm_probs.values()) if sdm_probs else 0.0
    use_sdm = sdm_max > 0.0 and sdm_weight > 0.0
    eff_sdm_w = sdm_weight if use_sdm else 0.0
    know_weight = 100 - EMPIRICAL_WEIGHT - eff_sdm_w

    # 적합도 요인 레지스트리 — 새 입력 레이어(토양/기후격자 등)는 (함수) 한 줄을
    # 추가하면 되고, 활성 요인의 가중치 합으로 자동 정규화된다(확장성 보장).
    factor_fns = [
        lambda sp: _climate_fit(sp, zone),
        lambda sp: _elevation_fit(sp, site.elevation_m),
        lambda sp: _slope_fit(sp, site.slope_deg),
        lambda sp: _aspect_fit(sp, site.aspect_dir),
        lambda sp: _purpose_fit(sp, goal),
    ]
    if site.soil_drainage is not None:
        factor_fns.append(lambda sp: _drainage_fit(sp, site.soil_drainage))

    recs: list[Recommendation] = []
    for sp in db:
        factors = [fn(sp) for fn in factor_fns]
        wsum = sum(f.weight for f in factors) or 1.0
        base = sum(f.score * f.weight for f in factors) / wsum  # 0~1 정규화

        # 경험적 근거(0~1): 인접 임분 점유율. 차별화 신호로 사용.
        ecount = emp_counts.get(sp.korean_name, 0.0)
        efrac = 0.0
        if total_emp > 0 and ecount > 0:
            efrac = min(1.0, (ecount / total_emp) * 2)  # 50% 점유 시 만점

        # SDM 데이터기반 확률(0~1, 정규화)
        sdm_p = float(sdm_probs.get(sp.korean_name, 0.0))
        sdm_norm = (sdm_p / sdm_max) if use_sdm else 0.0

        # 지식기반 + 경험적 + (선택)SDM 가중합
        total = base * know_weight + efrac * EMPIRICAL_WEIGHT
        if use_sdm:
            total += sdm_norm * eff_sdm_w
        total = min(100.0, total)

        # 기후 부적합(0점)이고 경험적·데이터 근거도 없으면 기본 제외
        climate_zero = factors[0].score == 0.0
        if climate_zero and ecount <= 0 and sdm_p < 0.1 and not include_unsuitable:
            continue

        recs.append(Recommendation(
            species=sp,
            total_score=total,
            factors=factors,
            empirical_count=int(round(ecount)),
            cautions=_cautions(sp, site),
            sdm_prob=sdm_p,
        ))

    recs.sort(key=lambda r: r.total_score, reverse=True)
    return recs[:top_k]
