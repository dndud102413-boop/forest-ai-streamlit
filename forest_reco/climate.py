"""
climate.py — 위도·고도 기반 식생기후대 판정

연구 결과(docs/research/climate.json)를 코드화한다. 현장 1점(GPS)만 있을 때의
대용(proxy) 규칙을 사용한다:

  유효위도(effLat) = 위도 + (고도m / 100) × 0.15
    └ 기온감률 0.55℃/100m 를 한반도 위도-기온 기울기(~0.7℃/위도)로 환산한 값.
  effLat → 기후대 1차 판정, 고산 임계로 한대(아고산) 확정.

WI(온량지수)는 직접 산출 불가하므로 effLat로 근사 추정치만 제시(설명용),
신뢰도는 'proxy(중)'로 표기한다. 인근 기상관측 평년값이 있으면 실제 WI로
대체하는 것이 정확하다.
"""
from __future__ import annotations

from dataclasses import dataclass

ZONES = ["난대", "온대남부", "온대중부", "온대북부", "한대(아고산)"]

# effLat 경계 (연구 zone_table 기반)
_LAT_BREAKS = [
    (35.0, "난대"),
    (36.5, "온대남부"),
    (38.0, "온대중부"),
    (40.0, "온대북부"),
]

# 고산 한대 진입 임계(위도에 따라 가변): 남부 높고 북부 낮음
def _subalpine_threshold(lat: float) -> float:
    # 남부(33도) ~1550m, 북부(40도) ~1250m 선형
    return 1550 - (lat - 33) * (300 / 7)


@dataclass
class ClimateZone:
    zone: str
    eff_lat: float
    warmth_index_est: float
    confidence: str          # proxy(중) / 관측보간(높음)
    detail: str

    def as_dict(self) -> dict:
        return {
            "기후대": self.zone,
            "유효위도": round(self.eff_lat, 3),
            "온량지수_추정": round(self.warmth_index_est, 0),
            "신뢰도": self.confidence,
            "근거": self.detail,
        }


def _zone_by_eff_lat(eff_lat: float) -> str:
    for brk, zone in _LAT_BREAKS:
        if eff_lat < brk:
            return zone
    return "한대(아고산)"


def _wi_estimate(eff_lat: float) -> float:
    """effLat로 온량지수 대략 추정(설명용, 근사)."""
    # 연구 매핑: effLat 35→~120, 36.5→~100, 38→~85, 40→~55
    pts = [(35.0, 120), (36.5, 100), (38.0, 85), (40.0, 55)]
    if eff_lat <= pts[0][0]:
        return 120 + (pts[0][0] - eff_lat) * 12
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if eff_lat <= x1:
            t = (eff_lat - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return max(20.0, 55 - (eff_lat - 40) * 12)


def classify_zone(lat: float, elevation_m: float | None = 0.0) -> ClimateZone:
    """위도·고도로 기후대 판정."""
    elev = float(elevation_m or 0.0)
    eff_lat = lat + (elev / 100.0) * 0.15
    zone = _zone_by_eff_lat(eff_lat)

    # 고산 한대 확정 보정
    if elev >= _subalpine_threshold(lat):
        zone = "한대(아고산)"

    wi = _wi_estimate(eff_lat)
    detail = (
        f"위도 {lat:.3f}° + 고도 {elev:.0f}m(감률 0.55℃/100m) → "
        f"유효위도 {eff_lat:.2f}° 적용. 온량지수 추정 ≈ {wi:.0f}."
    )
    return ClimateZone(zone=zone, eff_lat=eff_lat, warmth_index_est=wi,
                       confidence="proxy(중)", detail=detail)


def zone_distance(a: str, b: str) -> int:
    """두 기후대의 인접 거리(0=동일, 1=인접, ...). 적합도 판정에 사용."""
    try:
        return abs(ZONES.index(a) - ZONES.index(b))
    except ValueError:
        return 99
