"""
landslide_raster.py — 산사태위험지도(10m 래스터, 위험등급 1~5) 질의.

전체를 메모리에 올리지 않고 rasterio window read로 좌표 주변만 읽어 메모리를 절약한다.
점 위험등급 + 반경 내 위험등급 분포(1~2등급 비율)를 제공해 재해위험 관리방향에 사용.
(데스크탑/실데이터 전용 — light_mode에서는 로딩하지 않는다.)

위험등급(공식): 1=매우 높음 … 5=매우 낮음 (1·2등급이 고위험).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .config import SETTINGS, CRS_WGS84
from .geo import sample_raster, RasterSampleError

GRADE_LABELS = {1: "매우 높음", 2: "높음", 3: "보통", 4: "낮음", 5: "매우 낮음"}


class LandslideRaster:
    def __init__(self, dataset, settings=SETTINGS):
        self.ds = dataset
        self.settings = settings

    @classmethod
    def load(cls, path: Optional[Path] = None, settings=SETTINGS) -> Optional["LandslideRaster"]:
        import rasterio

        p = Path(path or settings.landslide_path)
        if not p.exists():
            return None
        return cls(rasterio.open(p), settings=settings)

    @staticmethod
    def _valid_grade(v) -> Optional[int]:
        if v is None:
            return None
        try:
            g = int(round(float(v)))
        except (TypeError, ValueError):
            return None
        return g if 1 <= g <= 5 else None

    def query(self, lon: float, lat: float, point_crs: str = CRS_WGS84) -> Optional[dict]:
        try:
            v = sample_raster(self.ds, lon, lat, point_crs=point_crs, method="nearest")
        except RasterSampleError:
            return None
        g = self._valid_grade(v)
        if g is None:
            return None
        return {"grade": g, "label": GRADE_LABELS.get(g), "high_risk": g in (1, 2)}

    def risk_summary(self, lon: float, lat: float, radius_m: float,
                     point_crs: str = CRS_WGS84) -> Optional[dict]:
        import numpy as np
        from rasterio.windows import Window
        from pyproj import Transformer

        try:
            tr = Transformer.from_crs(point_crs, self.ds.crs, always_xy=True)
            x, y = tr.transform(lon, lat)
            row, col = self.ds.index(x, y)
        except Exception:  # noqa: BLE001
            return None
        px = max(1, int(radius_m / abs(self.ds.res[0])))
        win = Window(col - px, row - px, 2 * px, 2 * px)
        try:
            arr = self.ds.read(1, window=win, boundless=True, fill_value=self.ds.nodata)
        except Exception:  # noqa: BLE001
            return None
        flat = arr.ravel()
        if self.ds.nodata is not None:
            flat = flat[flat != self.ds.nodata]
        valid = flat[(flat >= 1) & (flat <= 5)]
        if valid.size == 0:
            return None
        grades, counts = np.unique(valid, return_counts=True)
        dist = {int(g): int(c) for g, c in zip(grades, counts)}
        total = int(valid.size)
        high = sum(c for g, c in dist.items() if g in (1, 2))
        pt = self.query(lon, lat, point_crs)
        return {
            "radius_m": radius_m,
            "point_grade": pt["grade"] if pt else None,
            "point_label": pt["label"] if pt else None,
            "high_risk_ratio": round(high / total, 3),
            "distribution": dist,
            "n_cells": total,
        }
