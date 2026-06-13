"""site_detail_map.py — 상세 산림입지/토양도 위치 질의."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import SETTINGS, CRS_WGS84


DETAIL_FIELDS = {
    "SLTP_CD": "토양형코드",
    "STQLT_CD": "토양질코드",
    "RHGLT_GGRP": "기복군코드",
    "WTHR_CD": "풍화코드",
    "TPGRP_TPCD": "지형군코드",
    "CLZN_CD": "기후대코드",
    "PRRCK_LARG": "모암_대분류",
    "SOIL_DRNGE": "토양배수코드",
    "LOCTN_GRDN": "상세입지경사",
    "ALTTD_CD": "고도코드",
    "ACCMA_FOR": "퇴적양식코드",
    "WASH_CD": "침식코드",
    "SLANT_TYP": "사면형코드",
    "EIGHT_CD": "방위코드",
    "ROCK_EXDGR": "암석노출도",
    "RIDGE_VS": "능선계곡코드",
    "WIND_EXDGR": "바람노출도",
    "WTEFF_DGR": "수분영향도",
    "VLDTY_SLDP": "유효토심",
}


@dataclass
class SiteDetailQuery:
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


class SiteDetailMap:
    def __init__(self, gdf, settings=SETTINGS):
        self.gdf = gdf
        self.crs = gdf.crs
        self.settings = settings
        _ = self.gdf.sindex

    @classmethod
    def load(cls, path: Optional[Path] = None, settings=SETTINGS) -> Optional["SiteDetailMap"]:
        import geopandas as gpd

        p = Path(path or settings.site_detail_path)
        if not p.exists():
            return None
        return cls(gpd.read_file(p), settings=settings)

    def _to_local(self, lon: float, lat: float, point_crs: str):
        import geopandas as gpd
        from shapely.geometry import Point

        return gpd.GeoSeries([Point(lon, lat)], crs=point_crs).to_crs(self.crs).iloc[0]

    def query(self, lon: float, lat: float, point_crs: str = CRS_WGS84) -> SiteDetailQuery:
        local_pt = self._to_local(lon, lat, point_crs)
        cand_idx = list(self.gdf.sindex.query(local_pt, predicate="within"))
        if cand_idx:
            return self._row_to_query(self.gdf.iloc[cand_idx[0]], inside=True, dist=0.0)

        radius = 500.0
        b = local_pt.buffer(radius).bounds
        near_idx = list(self.gdf.sindex.intersection(b))
        if not near_idx:
            return SiteDetailQuery(found=False, inside_polygon=False)
        sub = self.gdf.iloc[near_idx]
        dists = sub.geometry.distance(local_pt)
        j = dists.idxmin()
        dmin = float(dists.loc[j])
        if dmin > radius:
            return SiteDetailQuery(found=False, inside_polygon=False, distance_m=dmin)
        return self._row_to_query(self.gdf.loc[j], inside=False, dist=dmin)

    def _row_to_query(self, row, inside: bool, dist: float) -> SiteDetailQuery:
        raw = {}
        attrs = {}
        for col, label in DETAIL_FIELDS.items():
            val = row[col] if col in row.index else None
            raw[col] = val
            attrs[label] = val
        return SiteDetailQuery(found=True, inside_polygon=inside, distance_m=dist,
                               attributes=attrs, raw=raw)
