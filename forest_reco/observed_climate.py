"""
observed_climate.py — 산악기상관측소 실측 기후(stations.csv) 보간 조회.

점 형태 관측소 자료를 위치별 기후 피처로 쓰기 위해 가까운 관측소 여러 개를
거리·좌표신뢰도 가중 평균(IDW)으로 섞는다. 원본 CSV는 그대로 두고, 있으면
data/derived/stations_verified.csv 같은 정제본을 우선 사용한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CONFIDENCE_WEIGHTS = {"high": 1.0, "med": 0.7, "low": 0.0}


def _haversine_km(lat1, lon1, lat2, lon2):
    """두 위경도 사이 거리(km)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Station:
    name: str
    lat: float
    lon: float
    elev_m: Optional[float] = None
    temp_c: Optional[float] = None
    precip_mm: Optional[float] = None
    humidity_pct: Optional[float] = None
    wind_ms: Optional[float] = None
    confidence: str = "med"
    geocode_source: str = ""

    @property
    def weight(self) -> float:
        return CONFIDENCE_WEIGHTS.get(str(self.confidence).lower(), 0.7)


class ObservedClimate:
    """산악기상관측소 실측 기후 포인트 집합 + 신뢰도 가중 IDW 조회."""

    def __init__(self, stations: list[Station], report: Optional[dict] = None):
        self.stations = stations
        self.report = report or {}
        import numpy as np
        self._lat = np.array([s.lat for s in stations], dtype="float64")
        self._lon = np.array([s.lon for s in stations], dtype="float64")
        self._weight = np.array([s.weight for s in stations], dtype="float64")

    def __len__(self):
        return len(self.stations)

    @classmethod
    def from_csv(
        cls,
        path: str | Path,
        *,
        exclude_low: bool = True,
        clean: bool = True,
    ) -> Optional["ObservedClimate"]:
        """stations.csv 로드. 저신뢰 좌표와 이상치는 원본 훼손 없이 로딩 단계에서 정리."""
        import csv as _csv
        p = Path(path)
        if not p.exists():
            return None
        out: list[Station] = []
        total = excluded_low = invalid_coord = cleaned_wind = 0
        with open(p, encoding="utf-8-sig") as f:
            for row in _csv.DictReader(f):
                total += 1
                try:
                    lat = float(row["lat"]); lon = float(row["lon"])
                except (TypeError, ValueError, KeyError):
                    invalid_coord += 1
                    continue
                confidence = str(row.get("confidence", "med") or "med").lower()
                if exclude_low and confidence == "low":
                    excluded_low += 1
                    continue

                def _f(k):
                    v = row.get(k, "")
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return None
                wind = _f("wind_ms")
                if clean and wind is not None and wind < 0:
                    wind = None
                    cleaned_wind += 1
                out.append(Station(
                    name=row.get("station", ""), lat=lat, lon=lon,
                    elev_m=_f("elev_m"),
                    temp_c=_f("temp_c"), precip_mm=_f("precip_mm"),
                    humidity_pct=_f("humidity_pct"), wind_ms=wind,
                    confidence=confidence,
                    geocode_source=row.get("geocode_source", ""),
                ))
        report = {
            "source_path": str(p),
            "source_rows": total,
            "station_count": len(out),
            "excluded_low": excluded_low,
            "invalid_coord": invalid_coord,
            "cleaned_negative_wind": cleaned_wind,
            "confidence_counts": {},
            "confidence_weights": CONFIDENCE_WEIGHTS,
        }
        for s in out:
            report["confidence_counts"][s.confidence] = \
                report["confidence_counts"].get(s.confidence, 0) + 1
        return cls(out, report=report) if out else None

    def idw(self, lat: float, lon: float, k: int = 6, power: float = 2.0) -> Optional[dict]:
        """역거리가중(IDW) 보간 — 가까운 k개 관측소를 거리·신뢰도 가중평균.

        nearest()(보로노이·계단식)와 달리 경계가 매끄럽고 여러 관측소를 섞는다.
        low 좌표는 기본 제외, med 좌표는 high보다 낮은 영향력으로 반영한다.
        """
        if not self.stations:
            return None
        import numpy as np
        dlat = self._lat - lat
        dlon = (self._lon - lon) * math.cos(math.radians(lat))
        d_km = np.sqrt(dlat ** 2 + dlon ** 2) * 111.0   # 도→km 근사(소영역)
        order = np.argsort(d_km)[:k]
        dk = d_km[order]
        if dk[0] < 1e-6:   # 관측소와 사실상 동일 지점이면 그 값
            return self._row(order[0], float(dk[0]))
        w = (1.0 / (dk ** power)) * self._weight[order]

        def _blend(attr):
            vals = np.array([getattr(self.stations[i], attr) for i in order], dtype="float64")
            m = (~np.isnan(vals)) & (w > 0)
            return float(np.sum(w[m] * vals[m]) / np.sum(w[m])) if m.any() else None

        confidence_mix: dict[str, int] = {}
        for i in order:
            c = self.stations[int(i)].confidence
            confidence_mix[c] = confidence_mix.get(c, 0) + 1
        return {
            "method": "idw_confidence", "n_used": int(len(order)),
            "nearest_km": round(float(dk[0]), 1),
            "temp_c": _blend("temp_c"), "precip_mm": _blend("precip_mm"),
            "humidity_pct": _blend("humidity_pct"), "wind_ms": _blend("wind_ms"),
            "confidence_mix": confidence_mix,
            "station_count": self.report.get("station_count", len(self.stations)),
            "excluded_low": self.report.get("excluded_low", 0),
            "cleaned_negative_wind": self.report.get("cleaned_negative_wind", 0),
        }

    def _row(self, j: int, dist_km: float) -> dict:
        s = self.stations[j]
        return {"method": "nearest", "station": s.name, "dist_km": round(dist_km, 1),
                "temp_c": s.temp_c, "precip_mm": s.precip_mm,
                "humidity_pct": s.humidity_pct, "wind_ms": s.wind_ms,
                "confidence": s.confidence, "elev_m": s.elev_m}

    def nearest(self, lat: float, lon: float) -> Optional[dict]:
        """좌표에서 가장 가까운 관측소의 실측 기후 + 거리(km)."""
        if not self.stations:
            return None
        import numpy as np
        # 빠른 1차 근사(평면 근사)로 최근접 후보를 고른 뒤 정확한 haversine로 확정.
        d2 = (self._lat - lat) ** 2 + ((self._lon - lon) * math.cos(math.radians(lat))) ** 2
        j = int(np.argmin(d2))
        s = self.stations[j]
        return {
            "station": s.name,
            "dist_km": round(_haversine_km(lat, lon, s.lat, s.lon), 1),
            "temp_c": s.temp_c,
            "precip_mm": s.precip_mm,
            "humidity_pct": s.humidity_pct,
            "wind_ms": s.wind_ms,
            "confidence": s.confidence,
            "elev_m": s.elev_m,
        }

    def quality_report(self) -> dict:
        """앱/보고서에 노출할 데이터 품질 요약."""
        return dict(self.report)
