"""
reliability.py — 추천 신뢰도 보완 지표 (데스크탑/로컬 전용)

기존 추천 결과를 바꾸지 않고, "추천이 얼마나 확실한지"를 설명하는 3가지 보조 지표와
이를 합친 종합 신뢰도를 계산한다.

  1. SDM 확률 차이 기반 신뢰도   — 모델이 1·2위 수종을 얼마나 확신하는가
  2. 주변 실제 임분 일치도        — 반경 내 실제 우점 수종과 추천이 얼마나 맞는가(면적가중)
  3. 반경 내 환경 다양성 지수     — 단일 좌표가 주변 환경을 대표할 수 있는가

설계 원칙
- 순수 계산 함수(무거운 GIS import 없음) → 단위테스트 용이. 데이터 조회는 호출부에서.
- 모든 지표는 독립적으로 실패해도 다른 지표·기본 추천에 영향 없음("분석 제한" 반환).
- 임계값은 전부 상수 → 데이터 분포를 보고 쉽게 조정 가능.
"""
from __future__ import annotations

import math
from typing import Optional

# ---------------------------------------------------------------------------
# 임계값 상수 (나중에 데이터 분포를 보고 조정)
# ---------------------------------------------------------------------------
# 1) SDM 확률 차이(p1 - p2)
PROB_GAP_HIGH = 0.20
PROB_GAP_MID = 0.10
# 2) 주변 임분 일치도
AGREE_TOP3_HIGH = 0.67
AGREE_TOP3_MID = 0.34
AGREE_TOP1_SHARE_HIGH = 0.30
AGREE_TOP1_SHARE_MID = 0.10
# 3) 환경 다양성 (각 지표를 0=낮음/1=보통/2=높음으로 점수화 → 평균)
ELEV_STD_LOW, ELEV_STD_MID = 30.0, 80.0      # 고도 표준편차(m)
SLOPE_STD_LOW, SLOPE_STD_MID = 5.0, 10.0     # 경사 표준편차(도)
SHANNON_LOW, SHANNON_MID = 0.8, 1.2          # 수종 Shannon 다양도(자연로그)

# 반경 옵션(m)과 기본값
RADIUS_OPTIONS = (500, 1000, 3000)
DEFAULT_RADIUS_M = 1000

LEVEL_HIGH, LEVEL_MID, LEVEL_LOW, LEVEL_NA = "높음", "보통", "낮음", "분석 제한"

# 등급 → 점수(종합 산정용). 다양성은 '낮을수록 신뢰' 이므로 역방향 표를 둔다.
_PTS = {LEVEL_HIGH: 2, LEVEL_MID: 1, LEVEL_LOW: 0}
_PTS_INV = {LEVEL_LOW: 2, LEVEL_MID: 1, LEVEL_HIGH: 0}


def _limited(message: str, radius_m: Optional[int] = None) -> dict:
    d = {"level": LEVEL_NA, "message": message}
    if radius_m is not None:
        d["radius_m"] = radius_m
    return d


def _round(v, n=2):
    return round(float(v), n) if v is not None else None


# ---------------------------------------------------------------------------
# 1. SDM 확률 차이 기반 신뢰도
# ---------------------------------------------------------------------------
def sdm_probability_gap(sdm_probs: dict) -> dict:
    """SDM 원확률(블렌딩 전)에서 1위·2위 수종 확률 차이로 신뢰도 등급화."""
    if not sdm_probs:
        return _limited("SDM 확률값이 없어 추천 신뢰도(확률 차이)를 계산할 수 없습니다.")
    items = sorted(sdm_probs.items(), key=lambda kv: kv[1], reverse=True)
    top1_sp, p1 = items[0][0], float(items[0][1])
    top2_sp, p2 = (items[1][0], float(items[1][1])) if len(items) >= 2 else (None, 0.0)
    gap = round(p1 - p2, 4)
    if gap >= PROB_GAP_HIGH:
        level = LEVEL_HIGH
        msg = "1위 수종과 2위 수종의 확률 차이가 커서 모델 추천이 비교적 안정적입니다."
    elif gap >= PROB_GAP_MID:
        level = LEVEL_MID
        msg = "상위 수종 간 확률 차이가 중간 수준입니다. 후보 Top-3를 함께 검토하세요."
    else:
        level = LEVEL_LOW
        msg = ("상위 수종 간 예측 확률 차이가 작아 단일 수종 확정 추천은 어렵습니다. "
               "후보 Top-3를 함께 검토하는 것이 적절합니다.")
    return {
        "top1_species": top1_sp, "top1_probability": round(p1, 3),
        "top2_species": top2_sp, "top2_probability": round(p2, 3),
        "gap": gap, "level": level, "message": msg,
    }


# ---------------------------------------------------------------------------
# 2. 주변 실제 임분과 추천 결과의 일치도 (면적가중)
# ---------------------------------------------------------------------------
def neighbor_agreement(area_shares: dict, recommended_top3, recommended_top1,
                       radius_m: int) -> dict:
    """면적가중 수종비율(area_shares, KB수종명으로 정규화됨)과 추천 결과의 일치도."""
    if not area_shares:
        return _limited("반경 내 임상도 분포가 없어 주변 임분 일치도를 계산할 수 없습니다.", radius_m)
    ranked = sorted(area_shares.items(), key=lambda kv: kv[1], reverse=True)
    top5 = [k for k, _ in ranked[:5]]
    rec3 = [s for s in (recommended_top3 or []) if s][:3]
    matched = [s for s in rec3 if s in top5]
    top3_agreement = round(len(matched) / len(rec3), 3) if rec3 else 0.0
    top1_share = round(float(area_shares.get(recommended_top1, 0.0)), 3) if recommended_top1 else 0.0

    if top3_agreement >= AGREE_TOP3_HIGH or top1_share >= AGREE_TOP1_SHARE_HIGH:
        level = LEVEL_HIGH
        msg = "추천 수종이 주변 실제 임분에서도 높은 비율로 나타나 추천의 공간적 근거가 강한 편입니다."
    elif top3_agreement >= AGREE_TOP3_MID or top1_share >= AGREE_TOP1_SHARE_MID:
        level = LEVEL_MID
        msg = "추천 수종이 주변 임분과 부분적으로 일치합니다. 후보 Top-3를 함께 검토하세요."
    else:
        level = LEVEL_LOW
        msg = ("추천 수종과 주변 실제 우점 수종이 다릅니다. 입지 조건은 추천 수종에 적합할 수 "
               "있으나, 실제 주변 식생 분포와 차이가 있으므로 현장 확인이 필요합니다.")
    return {
        "radius_m": radius_m,
        "top_species_area_share": {k: round(v, 3) for k, v in ranked[:3]},
        "recommended_top1_share": top1_share,
        "top3_agreement": top3_agreement,
        "level": level, "message": msg,
    }


# ---------------------------------------------------------------------------
# 3. 반경 내 환경 다양성 지수
# ---------------------------------------------------------------------------
def shannon_index(shares: dict) -> float:
    """비율 dict로부터 Shannon 다양도(자연로그). 비어 있으면 0."""
    ps = [float(p) for p in (shares or {}).values() if p and p > 0]
    s = sum(ps)
    if s <= 0:
        return 0.0
    ps = [p / s for p in ps]
    return round(-sum(p * math.log(p) for p in ps), 4)


def _grade3(value, low_th, mid_th) -> Optional[int]:
    """value < low → 0(낮음), < mid → 1(보통), else 2(높음)."""
    if value is None:
        return None
    if value < low_th:
        return 0
    if value < mid_th:
        return 1
    return 2


def environment_diversity(elevation_std, slope_std, species_shannon,
                          radius_m: int, **extra) -> dict:
    """고도·경사 변동성 + 수종 Shannon을 점수화(AND 아님)해 다양성 등급 산정."""
    parts = [
        _grade3(elevation_std, ELEV_STD_LOW, ELEV_STD_MID),
        _grade3(slope_std, SLOPE_STD_LOW, SLOPE_STD_MID),
        _grade3(species_shannon, SHANNON_LOW, SHANNON_MID),
    ]
    scores = [s for s in parts if s is not None]
    if not scores:
        return _limited("반경 내 지형/임분 데이터가 없어 환경 다양성을 계산할 수 없습니다.", radius_m)
    avg = sum(scores) / len(scores)
    if avg < 0.67:
        level = LEVEL_LOW
        msg = "주변 환경이 비교적 균질하여 단일 좌표 추천의 대표성이 높습니다."
    elif avg < 1.34:
        level = LEVEL_MID
        msg = "일부 환경 차이가 있어 추천 수종 Top-3를 함께 검토하는 것이 적절합니다."
    else:
        level = LEVEL_HIGH
        msg = ("반경 내 고도·경사 변화가 크고 수종 구성이 혼재되어 단일 좌표만으로 주변 전체를 "
               "대표하기 어렵습니다. 식재 전 세부 지점별 현장조사가 필요합니다.")
    out = {
        "radius_m": radius_m,
        "elevation_std": _round(elevation_std),
        "slope_std": _round(slope_std),
        "species_shannon": _round(species_shannon, 3),
        "level": level, "message": msg,
    }
    for k in ("elevation_mean", "elevation_range", "slope_mean", "aspect_distribution"):
        if k in extra and extra[k] is not None:
            out[k] = extra[k] if k == "aspect_distribution" else _round(extra[k])
    return out


# ---------------------------------------------------------------------------
# 4. 종합 추천 신뢰도
# ---------------------------------------------------------------------------
def overall_reliability(gap_res: dict, neighbor_res: dict, diversity_res: dict) -> dict:
    pts = [
        _PTS.get((gap_res or {}).get("level")),
        _PTS.get((neighbor_res or {}).get("level")),
        _PTS_INV.get((diversity_res or {}).get("level")),  # 다양성은 역방향
    ]
    vals = [p for p in pts if p is not None]
    if not vals:
        return _limited("신뢰도 지표를 충분히 계산하지 못해 종합 신뢰도를 산정할 수 없습니다.")
    avg = sum(vals) / len(vals)
    if avg >= 1.34:
        level = LEVEL_HIGH
        msg = "SDM·주변 임분·환경 균질성이 모두 추천 결과를 비교적 잘 뒷받침합니다."
    elif avg >= 0.67:
        level = LEVEL_MID
        msg = "추천 결과는 일정 부분 뒷받침되나, 후보 Top-3 비교와 현장 확인을 함께 권장합니다."
    else:
        level = LEVEL_LOW
        msg = ("SDM 확신도·주변 임분 일치·환경 균질성 중 다수가 낮아 단일 좌표 추천의 불확실성이 "
               "큽니다. 현장 토양·배수·병해충 피해 여부를 추가로 확인해야 합니다.")
    return {"level": level, "message": msg}


# ---------------------------------------------------------------------------
# 오케스트레이터 — 데이터 조회 + 4개 지표 결합 (각 단계 독립 fallback)
# ---------------------------------------------------------------------------
def _normalize_shares(raw: dict, db) -> dict:
    """면적비율의 임상도 수종명(KOFTR_NM)을 KB 수종명으로 매핑·합산."""
    if not raw:
        return {}
    out: dict = {}
    for k, v in raw.items():
        name = k
        if db is not None:
            try:
                sp = db.match(k)
                if sp:
                    name = sp.korean_name
            except Exception:  # noqa: BLE001
                pass
        out[name] = out.get(name, 0.0) + float(v)
    return out


def compute_reliability(sources, site, rec_dicts, sdm_probs,
                        radius_m: int = DEFAULT_RADIUS_M, db=None) -> dict:
    """4개 신뢰도 지표를 계산해 합친 dict 반환. 어떤 단계가 실패해도 앱은 멈추지 않는다."""
    db = db if db is not None else getattr(sources, "db", None)
    top3 = [r.get("수종") for r in (rec_dicts or [])[:3] if r.get("수종")]
    top1 = top3[0] if top3 else None

    # 1) SDM 확률 차이
    try:
        gap = sdm_probability_gap(sdm_probs or {})
    except Exception:  # noqa: BLE001
        gap = _limited("SDM 확률 차이 계산 중 오류가 발생했습니다.")

    # 2) 주변 임분 일치도 (면적가중)
    shares: dict = {}
    try:
        raw = sources.forest.species_area_shares(site.lon, site.lat, radius_m)
        shares = _normalize_shares(raw, db)
        neighbor = neighbor_agreement(shares, top3, top1, radius_m)
    except Exception:  # noqa: BLE001
        neighbor = _limited("주변 임분 일치도를 현재 데이터 범위에서 계산할 수 없습니다.", radius_m)

    # 3) 환경 다양성
    try:
        tstats = sources.terrain.radius_stats(site.lon, site.lat, radius_m) or {}
        shannon = shannon_index(shares) if shares else None
        diversity = environment_diversity(
            tstats.get("elevation_std"), tstats.get("slope_std"), shannon, radius_m,
            elevation_mean=tstats.get("elevation_mean"),
            elevation_range=tstats.get("elevation_range"),
            slope_mean=tstats.get("slope_mean"),
            aspect_distribution=tstats.get("aspect_distribution"))
    except Exception:  # noqa: BLE001
        diversity = _limited("환경 다양성 분석을 현재 데이터 범위에서 계산할 수 없습니다.", radius_m)

    # 4) 종합
    try:
        overall = overall_reliability(gap, neighbor, diversity)
    except Exception:  # noqa: BLE001
        overall = _limited("종합 신뢰도 산정 중 오류가 발생했습니다.")

    return {
        "radius_m": radius_m,
        "sdm_probability_gap": gap,
        "neighbor_agreement": neighbor,
        "environment_diversity": diversity,
        "overall_reliability": overall,
    }
