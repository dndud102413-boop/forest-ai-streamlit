"""
afforestation_map.py — 맞춤형조림지도(산림청 공식 적지적수 추천) 위치 질의.

scripts/prepare_extra_data.py가 만든 경량 GeoPackage를 읽어, 좌표 위치의 산림청
공식 추천 수종(대표/유사/추가)을 반환한다. SDM 추천과 비교해 추천 신뢰도를 보강한다.
(데스크탑/실데이터 전용 — light_mode에서는 로딩하지 않는다.)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import SETTINGS, CRS_WGS84

CLZN_NAMES = {"1": "온대북부", "2": "온대중부", "3": "온대남부", "4": "난대"}


def _split_species(v) -> list[str]:
    if v is None:
        return []
    s = str(v).strip()
    if not s or s.lower() == "none":
        return []
    for sep in (";", "/", "|"):
        s = s.replace(sep, ",")
    return [t.strip() for t in s.split(",") if t.strip()]


@dataclass
class AfforestationQuery:
    found: bool
    inside_polygon: bool = False
    distance_m: float = 0.0
    climate_zone: Optional[str] = None
    representative: list = field(default_factory=list)   # 대표수종(적지적수)
    similar: list = field(default_factory=list)          # 유사수종
    additional: list = field(default_factory=list)       # 추가수종
    all_species: list = field(default_factory=list)      # 위 3종 합집합(비교용)

    def as_dict(self) -> dict:
        return {
            "found": self.found,
            "inside_polygon": self.inside_polygon,
            "distance_m": round(self.distance_m, 1),
            "기후대": self.climate_zone,
            "대표수종": self.representative,
            "유사수종": self.similar,
            "추가수종": self.additional,
            "공식수종전체": self.all_species,
        }


class AfforestationMap:
    """맞춤형조림지도 GeoDataFrame 래퍼."""

    def __init__(self, gdf, settings=SETTINGS):
        self.gdf = gdf
        self.crs = gdf.crs
        self.settings = settings
        _ = self.gdf.sindex

    @classmethod
    def load(cls, path: Optional[Path] = None, settings=SETTINGS) -> Optional["AfforestationMap"]:
        import geopandas as gpd

        p = Path(path or settings.afforestation_path)
        if not p.exists():
            return None
        return cls(gpd.read_file(p), settings=settings)

    def _to_local(self, lon: float, lat: float, point_crs: str):
        import geopandas as gpd
        from shapely.geometry import Point

        return gpd.GeoSeries([Point(lon, lat)], crs=point_crs).to_crs(self.crs).iloc[0]

    def query(self, lon: float, lat: float, point_crs: str = CRS_WGS84) -> AfforestationQuery:
        local_pt = self._to_local(lon, lat, point_crs)
        cand = list(self.gdf.sindex.query(local_pt, predicate="within"))
        if cand:
            return self._row(self.gdf.iloc[cand[0]], inside=True, dist=0.0)
        b = local_pt.buffer(1000.0).bounds
        near = list(self.gdf.sindex.intersection(b))
        if not near:
            return AfforestationQuery(found=False)
        sub = self.gdf.iloc[near]
        dists = sub.geometry.distance(local_pt)
        j = dists.idxmin()
        dmin = float(dists.loc[j])
        if dmin > 1000.0:
            return AfforestationQuery(found=False, distance_m=dmin)
        return self._row(self.gdf.loc[j], inside=False, dist=dmin)

    def _row(self, row, inside: bool, dist: float) -> AfforestationQuery:
        def g(col):
            return row[col] if col in row.index else None

        rep = _split_species(g("RPRSN_KOFT"))
        sim = _split_species(g("S_LRT_KOFT"))
        add = _split_species(g("ADDTN_KOFT")) + _split_species(g("KOFTR_LIST"))
        seen, allsp = set(), []
        for s in rep + sim + add:
            if s not in seen:
                seen.add(s)
                allsp.append(s)
        clzn = g("CLZN_CD")
        return AfforestationQuery(
            found=True, inside_polygon=inside, distance_m=dist,
            climate_zone=CLZN_NAMES.get(str(clzn).strip() if clzn is not None else "", None),
            representative=rep, similar=sim, additional=add, all_species=allsp,
        )
