"""Forest management history layers: planting, tending, and disease points."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional
import zlib

from .config import SETTINGS, CRS_WGS84


CURRENT_YEAR = date.today().year


def _num(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _code(v) -> float:
    if v is None:
        return -1.0
    s = str(v).strip()
    if not s:
        return -1.0
    return float(zlib.crc32(s.encode("utf-8")) % 10000)


@dataclass
class ManagementQuery:
    found: bool
    planting: dict = field(default_factory=dict)
    tending: dict = field(default_factory=dict)
    disease: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "found": self.found,
            "planting": self.planting,
            "tending": self.tending,
            "disease": self.disease,
        }

    def feature_row(self) -> list[float]:
        p = self.planting or {}
        t = self.tending or {}
        d = self.disease or {}
        plant_area = _num(p.get("area_m2"))
        plant_count = _num(p.get("tree_count"))
        density = (plant_count / plant_area * 10000.0) if plant_area > 0 else 0.0
        return [
            1.0 if p else 0.0,
            _num(p.get("year")),
            max(0.0, CURRENT_YEAR - _num(p.get("year"), CURRENT_YEAR)) if p else 0.0,
            _code(p.get("species")),
            density,
            _num(p.get("distance_m"), 9999.0),
            1.0 if t else 0.0,
            _num(t.get("year")),
            max(0.0, CURRENT_YEAR - _num(t.get("year"), CURRENT_YEAR)) if t else 0.0,
            _code(t.get("work_type")),
            _num(t.get("area_m2")),
            _num(t.get("distance_m"), 9999.0),
            _num(d.get("count_1km")),
            _num(d.get("infected_1km")),
            _num(d.get("controlled_1km")),
            _num(d.get("nearest_m"), 9999.0),
            _num(d.get("recent_year")),
        ]


class _PolygonLayer:
    def __init__(self, gdf, kind: str):
        self.gdf = gdf
        self.kind = kind
        self.crs = gdf.crs
        _ = self.gdf.sindex

    @classmethod
    def load(cls, path: Path, kind: str) -> Optional["_PolygonLayer"]:
        import geopandas as gpd

        if not Path(path).exists():
            return None
        return cls(gpd.read_file(path), kind=kind)

    def _to_local(self, lon: float, lat: float, point_crs: str):
        import geopandas as gpd
        from shapely.geometry import Point

        return gpd.GeoSeries([Point(lon, lat)], crs=point_crs).to_crs(self.crs).iloc[0]

    def query(self, lon: float, lat: float, point_crs: str = CRS_WGS84, radius_m: float = 500.0) -> dict:
        if self.gdf.empty:
            return {}
        pt = self._to_local(lon, lat, point_crs)
        cand_idx = list(self.gdf.sindex.query(pt, predicate="within"))
        inside = True
        if not cand_idx:
            inside = False
            cand_idx = list(self.gdf.sindex.intersection(pt.buffer(radius_m).bounds))
            if not cand_idx:
                return {}
        sub = self.gdf.iloc[cand_idx].copy()
        if inside:
            sub["_distance_m"] = 0.0
        else:
            sub["_distance_m"] = sub.geometry.distance(pt)
            sub = sub[sub["_distance_m"] <= radius_m]
            if sub.empty:
                return {}
        year_col = "사업년도"
        if year_col in sub.columns:
            sub["_year"] = sub[year_col].fillna(0).astype(float)
            sub = sub.sort_values(["_distance_m", "_year"], ascending=[True, False])
        else:
            sub = sub.sort_values("_distance_m")
        row = sub.iloc[0]
        if self.kind == "planting":
            return {
                "inside_polygon": bool(inside),
                "distance_m": round(float(row["_distance_m"]), 1),
                "year": int(row["사업년도"]) if "사업년도" in row and row["사업년도"] == row["사업년도"] else None,
                "species": row.get("조림수종"),
                "tree_count": _num(row.get("식재본수")),
                "area_m2": _num(row.get("조성면적")),
                "city": row.get("시군구"),
                "town": row.get("읍면동"),
                "project": row.get("사업명"),
            }
        return {
            "inside_polygon": bool(inside),
            "distance_m": round(float(row["_distance_m"]), 1),
            "year": int(row["사업년도"]) if "사업년도" in row and row["사업년도"] == row["사업년도"] else None,
            "work_type": row.get("작업종"),
            "area_m2": _num(row.get("작업면적")),
            "city": row.get("시군구"),
            "town": row.get("읍면동"),
            "project": row.get("사업명"),
        }

    def radius_summary(self, lon: float, lat: float, point_crs: str = CRS_WGS84,
                       radii_m: tuple[int, ...] = (500, 1000, 3000)) -> dict:
        if self.gdf.empty:
            return {}
        pt = self._to_local(lon, lat, point_crs)
        max_radius = max(radii_m)
        idx = list(self.gdf.sindex.intersection(pt.buffer(max_radius).bounds))
        out = {}
        if not idx:
            for r in radii_m:
                out[str(r)] = {"count": 0}
            return out
        sub = self.gdf.iloc[idx].copy()
        sub["_distance_m"] = sub.geometry.distance(pt)
        sub = sub[sub["_distance_m"] <= max_radius]
        for r in radii_m:
            rr = sub[sub["_distance_m"] <= r].copy()
            item = {"count": int(len(rr))}
            if not rr.empty:
                year_col = "사업년도"
                if year_col in rr.columns:
                    years = rr[year_col].dropna()
                    if not years.empty:
                        item["latest_year"] = int(float(years.max()))
                if self.kind == "planting":
                    if "조림수종" in rr.columns and rr["조림수종"].notna().any():
                        item["main_species"] = str(rr["조림수종"].mode().iloc[0])
                    if "조성면적" in rr.columns:
                        item["area_m2"] = round(float(rr["조성면적"].fillna(0).sum()), 1)
                else:
                    if "작업종" in rr.columns and rr["작업종"].notna().any():
                        item["main_work_type"] = str(rr["작업종"].mode().iloc[0])
                    if "작업면적" in rr.columns:
                        item["area_m2"] = round(float(rr["작업면적"].fillna(0).sum()), 1)
                item["nearest_m"] = round(float(rr["_distance_m"].min()), 1)
            out[str(r)] = item
        return out


class _DiseaseLayer:
    def __init__(self, gdf):
        self.gdf = gdf
        self.crs = gdf.crs
        _ = self.gdf.sindex

    @classmethod
    def load(cls, path: Path) -> Optional["_DiseaseLayer"]:
        import geopandas as gpd

        if not Path(path).exists():
            return None
        return cls(gpd.read_file(path))

    def _to_local(self, lon: float, lat: float, point_crs: str):
        import geopandas as gpd
        from shapely.geometry import Point

        return gpd.GeoSeries([Point(lon, lat)], crs=point_crs).to_crs(self.crs).iloc[0]

    def query(self, lon: float, lat: float, point_crs: str = CRS_WGS84, radius_m: float = 1000.0) -> dict:
        if self.gdf.empty:
            return {}
        pt = self._to_local(lon, lat, point_crs)
        idx = list(self.gdf.sindex.intersection(pt.buffer(radius_m).bounds))
        if not idx:
            nearest = self.gdf.sindex.nearest(pt, return_all=False)
            try:
                near_idx = [int(nearest[1][0])]
            except Exception:
                near_idx = list(nearest)
            if not near_idx:
                return {}
            sub = self.gdf.iloc[near_idx]
            d = float(sub.geometry.distance(pt).min())
            return {"count_1km": 0, "infected_1km": 0, "controlled_1km": 0, "nearest_m": round(d, 1), "recent_year": None}
        sub = self.gdf.iloc[idx].copy()
        sub["_distance_m"] = sub.geometry.distance(pt)
        sub = sub[sub["_distance_m"] <= radius_m]
        if sub.empty:
            return {"count_1km": 0, "infected_1km": 0, "controlled_1km": 0, "nearest_m": None, "recent_year": None}
        return {
            "count_1km": int(len(sub)),
            "infected_1km": int(sub.get("is_infected", 0).sum()),
            "controlled_1km": int(sub.get("is_control_done", 0).sum()),
            "nearest_m": round(float(sub["_distance_m"].min()), 1),
            "recent_year": int(sub["year"].max()) if "year" in sub.columns and sub["year"].notna().any() else None,
        }

    def radius_summary(self, lon: float, lat: float, point_crs: str = CRS_WGS84,
                       radii_m: tuple[int, ...] = (500, 1000, 3000)) -> dict:
        if self.gdf.empty:
            return {}
        pt = self._to_local(lon, lat, point_crs)
        max_radius = max(radii_m)
        idx = list(self.gdf.sindex.intersection(pt.buffer(max_radius).bounds))
        out = {}
        if not idx:
            for r in radii_m:
                out[str(r)] = {"count": 0, "infected": 0, "controlled": 0}
            return out
        sub = self.gdf.iloc[idx].copy()
        sub["_distance_m"] = sub.geometry.distance(pt)
        sub = sub[sub["_distance_m"] <= max_radius]
        for r in radii_m:
            rr = sub[sub["_distance_m"] <= r]
            item = {
                "count": int(len(rr)),
                "infected": int(rr.get("is_infected", 0).sum()) if not rr.empty else 0,
                "controlled": int(rr.get("is_control_done", 0).sum()) if not rr.empty else 0,
            }
            if not rr.empty:
                item["nearest_m"] = round(float(rr["_distance_m"].min()), 1)
                if "year" in rr.columns and rr["year"].notna().any():
                    item["recent_year"] = int(rr["year"].max())
            out[str(r)] = item
        return out


class ManagementLayers:
    def __init__(self, planting=None, tending=None, disease=None):
        self.planting = planting
        self.tending = tending
        self.disease = disease

    @classmethod
    def load(cls, settings=SETTINGS) -> Optional["ManagementLayers"]:
        planting = _PolygonLayer.load(settings.planting_path, "planting")
        tending = _PolygonLayer.load(settings.tending_path, "tending")
        disease = _DiseaseLayer.load(settings.disease_path)
        if not any((planting, tending, disease)):
            return None
        return cls(planting=planting, tending=tending, disease=disease)

    def query(self, lon: float, lat: float, point_crs: str = CRS_WGS84) -> ManagementQuery:
        planting = self.planting.query(lon, lat, point_crs) if self.planting else {}
        tending = self.tending.query(lon, lat, point_crs) if self.tending else {}
        disease = self.disease.query(lon, lat, point_crs) if self.disease else {}
        return ManagementQuery(
            found=bool(planting or tending or disease),
            planting=planting,
            tending=tending,
            disease=disease,
        )

    def radius_summary(self, lon: float, lat: float, point_crs: str = CRS_WGS84,
                       radii_m: tuple[int, ...] = (500, 1000, 3000)) -> dict:
        return {
            "radii_m": list(radii_m),
            "planting": self.planting.radius_summary(lon, lat, point_crs, radii_m) if self.planting else {},
            "tending": self.tending.radius_summary(lon, lat, point_crs, radii_m) if self.tending else {},
            "disease": self.disease.radius_summary(lon, lat, point_crs, radii_m) if self.disease else {},
        }


MANAGEMENT_FEATURES = [
    "planting_found", "planting_year", "planting_age", "planting_species_code",
    "planting_density_ha", "planting_distance_m",
    "tending_found", "tending_year", "tending_age", "tending_type_code",
    "tending_area_m2", "tending_distance_m",
    "disease_count_1km", "disease_infected_1km", "disease_controlled_1km",
    "disease_nearest_m", "disease_recent_year",
]
