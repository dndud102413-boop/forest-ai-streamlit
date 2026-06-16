"""
forest_function_map.py — 산림기능구분도(산림청 공식 산림기능) 위치 질의.

좌표의 공식 주기능(수원함양/산지재해방지/자연환경보전/목재생산/산림휴양/생활환경보전)과
기능별 평가점수, 절대보전지역 여부를 반환한다. 추천 목적 정렬·관리방향에 사용.
(데스크탑/실데이터 전용 — light_mode에서는 로딩하지 않는다.)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import SETTINGS, CRS_WGS84

PF_NAMES = {
    "01": "수원함양", "02": "산지재해방지", "03": "자연환경보전",
    "04": "목재생산", "05": "산림휴양", "06": "생활환경보전",
}
SCORE_FIELDS = {
    "WRCF": "수원함양", "FDMF": "산지재해방지", "EECF": "자연환경보전",
    "FRCF": "목재생산", "RHF": "산림휴양", "UEF": "생활환경보전",
}
# 추천 목적(GOALS) → 산림기능 부합 매핑(목적 정렬용)
GOAL_TO_FUNCTION = {
    "탄소흡수": "수원함양", "용재생산": "목재생산", "경관조경": "산림휴양",
    "사방방재": "산지재해방지", "생물다양성": "자연환경보전", "도시녹화": "생활환경보전",
}


@dataclass
class ForestFunctionQuery:
    found: bool
    inside_polygon: bool = False
    distance_m: float = 0.0
    primary_function: Optional[str] = None
    primary_code: Optional[str] = None
    is_absolute: bool = False             # 절대보전지역 여부
    scores: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "found": self.found,
            "inside_polygon": self.inside_polygon,
            "distance_m": round(self.distance_m, 1),
            "주기능": self.primary_function,
            "주기능코드": self.primary_code,
            "절대보전지역": self.is_absolute,
            "기능점수": self.scores,
        }


class ForestFunctionMap:
    """산림기능구분도 GeoDataFrame 래퍼."""

    def __init__(self, gdf, settings=SETTINGS):
        self.gdf = gdf
        self.crs = gdf.crs
        self.settings = settings
        _ = self.gdf.sindex

    @classmethod
    def load(cls, path: Optional[Path] = None, settings=SETTINGS) -> Optional["ForestFunctionMap"]:
        import geopandas as gpd

        p = Path(path or settings.function_path)
        if not p.exists():
            return None
        return cls(gpd.read_file(p), settings=settings)

    def _to_local(self, lon: float, lat: float, point_crs: str):
        import geopandas as gpd
        from shapely.geometry import Point

        return gpd.GeoSeries([Point(lon, lat)], crs=point_crs).to_crs(self.crs).iloc[0]

    def query(self, lon: float, lat: float, point_crs: str = CRS_WGS84) -> ForestFunctionQuery:
        local_pt = self._to_local(lon, lat, point_crs)
        cand = list(self.gdf.sindex.query(local_pt, predicate="within"))
        if cand:
            return self._row(self.gdf.iloc[cand[0]], inside=True, dist=0.0)
        b = local_pt.buffer(500.0).bounds
        near = list(self.gdf.sindex.intersection(b))
        if not near:
            return ForestFunctionQuery(found=False)
        sub = self.gdf.iloc[near]
        dists = sub.geometry.distance(local_pt)
        j = dists.idxmin()
        dmin = float(dists.loc[j])
        if dmin > 500.0:
            return ForestFunctionQuery(found=False, distance_m=dmin)
        return self._row(self.gdf.loc[j], inside=False, dist=dmin)

    def _row(self, row, inside: bool, dist: float) -> ForestFunctionQuery:
        def g(col):
            return row[col] if col in row.index else None

        pf = g("PF")
        code = str(pf).strip().zfill(2) if pf is not None and str(pf).strip() != "" else None
        scores = {}
        for col, name in SCORE_FIELDS.items():
            v = g(col)
            if v is not None:
                try:
                    scores[name] = round(float(v), 1)
                except (TypeError, ValueError):
                    pass
        a = g("A")
        return ForestFunctionQuery(
            found=True, inside_polygon=inside, distance_m=dist,
            primary_function=PF_NAMES.get(code, None) if code else None,
            primary_code=code, is_absolute=(str(a).strip().upper() == "A"),
            scores=scores,
        )
