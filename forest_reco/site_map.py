"""
site_map.py — 산림입지도(토양·모암·토심·토성 등) 위치 질의.

DATA015 산림입지도 원본은 수 GB라 앱에서 바로 쓰기 어렵다. scripts/prepare_site_data.py
가 만든 경량 GeoPackage를 읽어 GPS 좌표에서 해당 입지 속성을 빠르게 찾는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import SETTINGS, CRS_WGS84


SITE_FIELDS = {
    "PRRCK_LARG": "모암_대분류",
    "PRRCK_MDDL": "모암_중분류",
    "LOCTN_ALTT": "입지고도",
    "LOCTN_GRDN": "입지경사",
    "EIGHT_AGL": "입지방위각",
    "CLZN_CD": "기후대코드",
    "TPGRP_TPCD": "지형군코드",
    "PRDN_FOM_C": "퇴적양식코드",
    "SLANT_TYP": "사면형코드",
    "SLDPT_TPCD": "토심코드",
    "SCSTX_CD": "토성코드",
    "SLTP_CD": "토양형코드",
    "LDMARK_STN": "입지표준",
    "MAP_LABEL": "지도라벨",
}


@dataclass
class SiteQuery:
    found: bool
    inside_polygon: bool
    distance_m: float = 0.0
    attributes: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "found": self.found,
            "inside_polygon": self.inside_polygon,
            "distance_m": round(self.distance_m, 1),
            **self.attributes,
        }


class SiteMap:
    """산림입지도 GeoDataFrame 래퍼."""

    def __init__(self, gdf, settings=SETTINGS):
        self.gdf = gdf
        self.crs = gdf.crs
        self.settings = settings
        _ = self.gdf.sindex

    @classmethod
    def load(cls, path: Optional[Path] = None, settings=SETTINGS) -> Optional["SiteMap"]:
        import geopandas as gpd

        p = Path(path or settings.site_path)
        if not p.exists():
            return None
        return cls(gpd.read_file(p), settings=settings)

    def _to_local(self, lon: float, lat: float, point_crs: str):
        import geopandas as gpd
        from shapely.geometry import Point

        return gpd.GeoSeries([Point(lon, lat)], crs=point_crs).to_crs(self.crs).iloc[0]

    def query(self, lon: float, lat: float, point_crs: str = CRS_WGS84) -> SiteQuery:
        local_pt = self._to_local(lon, lat, point_crs)
        cand_idx = list(self.gdf.sindex.query(local_pt, predicate="within"))
        if cand_idx:
            return self._row_to_query(self.gdf.iloc[cand_idx[0]], inside=True, dist=0.0)

        radius = 500.0
        b = local_pt.buffer(radius).bounds
        near_idx = list(self.gdf.sindex.intersection(b))
        if not near_idx:
            return SiteQuery(found=False, inside_polygon=False)
        sub = self.gdf.iloc[near_idx]
        dists = sub.geometry.distance(local_pt)
        j = dists.idxmin()
        dmin = float(dists.loc[j])
        if dmin > radius:
            return SiteQuery(found=False, inside_polygon=False, distance_m=dmin)
        return self._row_to_query(self.gdf.loc[j], inside=False, dist=dmin)

    def _row_to_query(self, row, inside: bool, dist: float) -> SiteQuery:
        raw = {}
        attrs = {}
        for col, label in SITE_FIELDS.items():
            val = row[col] if col in row.index else None
            raw[col] = val
            attrs[label] = val
        return SiteQuery(found=True, inside_polygon=inside, distance_m=dist,
                         attributes=attrs, raw=raw)
