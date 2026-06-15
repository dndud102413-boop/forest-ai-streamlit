"""
forest_map.py — 임상도(벡터 폴리곤) 적재 및 위치 질의

임상도는 래스터 격자가 아니라 *벡터 폴리곤* 이다. 따라서 위치 질의는
point-in-polygon 으로 푼다. 원본 노트북은 매 호출마다 모든 폴리곤과의
거리를 계산(O(N))하여 느렸고, 좌표계/예외 처리가 분산돼 있었다. 여기서는:

- 표준 컬럼(FRTP_NM, KOFTR_NM, DMCLS_NM, AGCLS_NM, DNST_NM)을 정규화
- geopandas 공간 인덱스(sjoin)로 포함 폴리곤을 빠르게 탐색
- 폴리곤 밖이면 반경 내 최근접 임분을 거리와 함께 폴백 제공
- 인접 반경 내 수종 빈도(경험적 추천 근거)를 집계
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from .config import SETTINGS, CRS_WGS84

# 표준 임상도 속성 컬럼 (한글 라벨)
FOREST_FIELDS = {
    "FRTP_NM": "임종",
    "KOFTR_NM": "수종",
    "DMCLS_NM": "경급",
    "AGCLS_NM": "영급",
    "DNST_NM": "밀도",
}


@dataclass
class ForestQuery:
    """임상도 위치 질의 결과."""

    found: bool
    inside_polygon: bool                 # 폴리곤 내부 여부
    distance_m: float = 0.0              # 폴백 시 최근접 임분까지 거리
    attributes: dict = field(default_factory=dict)   # 한글 라벨 → 값
    raw: dict = field(default_factory=dict)          # 원본 컬럼 → 값

    def as_dict(self) -> dict:
        return {
            "found": self.found,
            "inside_polygon": self.inside_polygon,
            "distance_m": round(self.distance_m, 1),
            **self.attributes,
        }


class ForestMap:
    """임상도 GeoDataFrame 래퍼."""

    def __init__(self, gdf, settings=SETTINGS):
        import warnings

        if gdf.crs is None:
            fallback = settings.forest_crs_fallback
            # .prj가 없으면 좌표계를 '추측'하게 되는데, 5179로 가정했는데 실제가
            # 5181(중부원점)이면 좌표가 1000km+ 어긋나 set_crs(라벨만 변경)로는
            # 모든 질의가 예외 없이 '데이터 없음'처럼 무음 실패한다. → 시끄럽게 경고.
            warnings.warn(
                f"임상도에 좌표계(.prj)가 없어 {fallback}로 가정합니다. 배포본이 다르면"
                f"(예: 중부원점 EPSG:5181) 위치 질의가 무음 실패할 수 있으니 "
                f"settings.forest_crs_fallback를 확인하세요.", stacklevel=2)
            gdf = gdf.set_crs(fallback)
            self._check_bounds_consistency(gdf, fallback)
        self.gdf = gdf
        self.crs = gdf.crs
        self.settings = settings
        # 공간 인덱스 강제 생성 (최초 질의 지연 방지)
        _ = self.gdf.sindex

    @staticmethod
    def _check_bounds_consistency(gdf, crs):
        """가정한 좌표계와 데이터 좌표 범위가 명백히 불일치하면 즉시 에러(무음 실패 차단)."""
        try:
            epsg = gdf.crs.to_epsg()
        except Exception:  # noqa: BLE001
            epsg = None
        minx, miny, maxx, maxy = gdf.total_bounds
        if str(crs).endswith("5179") or epsg == 5179:
            # EPSG:5179(UTM-K) 한반도: x≈7e5~1.4e6, y≈1.5e6~2.2e6
            if maxx < 5e5 or maxy < 1e6:
                raise ValueError(
                    f"좌표 범위(x {minx:.0f}~{maxx:.0f}, y {miny:.0f}~{maxy:.0f})가 "
                    f"EPSG:5179와 맞지 않습니다. 실제 좌표계(예: 중부원점 EPSG:5181)를 "
                    f"settings.forest_crs_fallback에 지정하세요.")

    # ---- 생성자 ----
    @classmethod
    def load(cls, paths: Optional[list[Path]] = None, settings=SETTINGS) -> "ForestMap":
        import geopandas as gpd

        paths = paths or settings.forest_paths()
        frames = []
        crs0 = None
        for p in paths:
            g = gpd.read_file(p)
            if crs0 is None:
                crs0 = g.crs
            elif g.crs != crs0:
                g = g.to_crs(crs0)
            frames.append(g)
        if not frames:
            raise FileNotFoundError(f"임상도 파일을 찾을 수 없습니다: {paths}")
        merged = pd.concat(frames, ignore_index=True)
        gdf = gpd.GeoDataFrame(merged, geometry="geometry", crs=crs0)
        return cls(gdf, settings=settings)

    # ---- 질의 ----
    def _to_local(self, lon: float, lat: float, point_crs: str):
        import geopandas as gpd
        from shapely.geometry import Point

        pt = gpd.GeoSeries([Point(lon, lat)], crs=point_crs).to_crs(self.crs)
        return pt.iloc[0]

    def query(self, lon: float, lat: float, point_crs: str = CRS_WGS84) -> ForestQuery:
        """위치(point_crs 기준)의 임분 속성을 반환. 폴리곤 밖이면 최근접 폴백."""
        local_pt = self._to_local(lon, lat, point_crs)

        # 공간 인덱스로 포함 폴리곤 탐색.
        # 주의: sindex.query(point, predicate=...) 의 술어는 point.predicate(polygon)
        # 으로 적용된다. 따라서 "점이 폴리곤 안"은 predicate="within"(=point.within(poly))
        # 이어야 한다. ("contains"는 point.contains(poly)라 항상 거짓 → 버그)
        cand_idx = list(self.gdf.sindex.query(local_pt, predicate="within"))
        if cand_idx:
            row = self.gdf.iloc[cand_idx[0]]
            return self._row_to_query(row, inside=True, dist=0.0)

        # 폴백: 반경 내 최근접 임분
        radius = self.settings.nearest_search_radius_m
        # 인덱스로 반경 박스 후보만 거리계산 (전수계산 회피)
        from shapely.geometry import box

        b = local_pt.buffer(radius).bounds
        near_idx = list(self.gdf.sindex.intersection(b))
        if not near_idx:
            return ForestQuery(found=False, inside_polygon=False)

        sub = self.gdf.iloc[near_idx]
        dists = sub.geometry.distance(local_pt)
        j = dists.idxmin()
        dmin = float(dists.loc[j])
        if dmin > radius:
            return ForestQuery(found=False, inside_polygon=False, distance_m=dmin)
        return self._row_to_query(self.gdf.loc[j], inside=False, dist=dmin)

    def _row_to_query(self, row, inside: bool, dist: float) -> ForestQuery:
        raw = {}
        attrs = {}
        for col, label in FOREST_FIELDS.items():
            val = row[col] if col in row.index else None
            raw[col] = val
            attrs[label] = val
        return ForestQuery(
            found=True, inside_polygon=inside, distance_m=dist,
            attributes=attrs, raw=raw,
        )

    def neighborhood_species(
        self, lon: float, lat: float, point_crs: str = CRS_WGS84,
        radius_m: Optional[float] = None,
    ) -> dict[str, int]:
        """
        반경 내 임분들의 수종(KOFTR_NM) 빈도. 경험적 추천 근거로 사용.
        "이 부근에서 실제로 잘 자라고 있는 수종" 신호.
        """
        radius_m = radius_m or self.settings.neighborhood_radius_m
        local_pt = self._to_local(lon, lat, point_crs)
        b = local_pt.buffer(radius_m).bounds
        near_idx = list(self.gdf.sindex.intersection(b))
        if not near_idx:
            return {}
        sub = self.gdf.iloc[near_idx]
        within = sub[sub.geometry.distance(local_pt) <= radius_m]
        if "KOFTR_NM" not in within.columns or within.empty:
            return {}
        counts = within["KOFTR_NM"].value_counts()
        return {str(k): int(v) for k, v in counts.items()}

    def species_area_shares(
        self, lon: float, lat: float, radius_m: float,
        point_crs: str = CRS_WGS84,
    ) -> dict[str, float]:
        """
        반경 buffer와 교차하는 임상도 폴리곤의 **면적가중** 수종비율(KOFTR_NM 기준).
        반환: {수종명: 0~1 비율}, 합 = 1.0. 반경 내 임분이 없으면 {}.
        (신뢰도 모듈의 '주변 임분 일치도' 계산에 사용. 좌표계가 미터(5179)라 면적 정확.)
        """
        local_pt = self._to_local(lon, lat, point_crs)
        buf = local_pt.buffer(radius_m)
        near_idx = list(self.gdf.sindex.intersection(buf.bounds))
        if not near_idx or "KOFTR_NM" not in self.gdf.columns:
            return {}
        sub = self.gdf.iloc[near_idx]
        # 면적은 buffer와의 교집합 면적으로 가중(폴리곤이 반경에 일부만 걸쳐도 정확)
        inter_area = sub.geometry.intersection(buf).area
        sub = sub.assign(_inter_area=inter_area.values)
        sub = sub[sub["_inter_area"] > 0]
        if sub.empty:
            return {}
        grouped = sub.groupby("KOFTR_NM")["_inter_area"].sum()
        total = float(grouped.sum())
        if total <= 0:
            return {}
        return {str(k): float(v) / total for k, v in grouped.items()}
