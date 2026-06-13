"""
terrain.py — DEM(래스터)에서 고도·경사·향 질의

DEM은 래스터이므로 geo.sample_raster()의 좌표계 변환 + 경계검사 + nodata
처리를 그대로 활용한다. 경사/향은 미터 단위 투영좌표계에서 계산해야 정확하므로,
DEM이 지리좌표계(4326)면 내부적으로 5179로 재투영한 배열로 경사/향을 만든다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from .config import SETTINGS, CRS_WGS84, CRS_KOREA_TM
from .geo import sample_raster, compute_slope_aspect, aspect_to_direction, RasterSampleError


@dataclass
class TerrainQuery:
    found: bool
    elevation_m: Optional[float] = None
    slope_deg: Optional[float] = None
    aspect_deg: Optional[float] = None
    aspect_dir: str = "평지"
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "고도": round(self.elevation_m, 1) if self.elevation_m is not None else None,
            "경사": round(self.slope_deg, 1) if self.slope_deg is not None else None,
            "향_도": round(self.aspect_deg, 1) if self.aspect_deg is not None else None,
            "향": self.aspect_dir,
            "found": self.found,
        }


class Terrain:
    """DEM 래스터 래퍼. 경사/향 배열을 1회만 계산해 캐시."""

    def __init__(self, dataset, settings=SETTINGS):
        self.ds = dataset
        self.settings = settings
        self._elev = dataset.read(1)
        self._slope = None
        self._aspect = None
        self._slope_ds = None  # 경사/향 계산에 사용한 (재투영) 데이터셋

    @classmethod
    def load(cls, path: Optional[Path] = None, settings=SETTINGS) -> "Terrain":
        import rasterio

        path = Path(path or settings.dem_path)
        ds = rasterio.open(path)
        return cls(ds, settings=settings)

    # ---- 경사/향 준비 (lazy) ----
    def _ensure_slope_aspect(self):
        if self._slope is not None:
            return
        import warnings
        import rasterio
        from rasterio.crs import CRS as RCRS
        from rasterio.warp import calculate_default_transform, reproject, Resampling

        # 좌표계 결정. CRS가 없으면(.prj 결손) 해상도로 추정: 도(degree)처럼 작으면
        # 지리좌표(4326), 아니면 미터 투영. 추정 없이 진행하면 지리좌표를 투영으로
        # 오인해 경사/향이 '도 단위 해상도'로 계산돼 비현실적으로 커진다.
        src_crs = self.ds.crs
        if src_crs is None:
            assumed = CRS_WGS84 if abs(self.ds.res[0]) < 0.05 else CRS_KOREA_TM
            warnings.warn(
                f"DEM에 좌표계가 없어 해상도({self.ds.res[0]})로 보아 {assumed}로 가정합니다. "
                f"실제와 다르면 경사/향이 왜곡되니 확인하세요.", stacklevel=2)
            src_crs = RCRS.from_user_input(assumed)

        # 미터 단위 좌표계면 그대로, 지리좌표(도)면 5179로 재투영해서 계산.
        if not src_crs.is_geographic:
            arr = self._elev.astype("float64")
            xres, yres = self.ds.res
            self._slope, self._aspect = compute_slope_aspect(
                arr, abs(xres), abs(yres), nodata=self.ds.nodata
            )
            self._slope_ds = self.ds
            return

        # 4326 → 5179 재투영 후 경사/향 계산
        dst_crs = CRS_KOREA_TM
        transform, w, h = calculate_default_transform(
            src_crs, dst_crs, self.ds.width, self.ds.height, *self.ds.bounds
        )
        dst = np.full((h, w), np.nan, dtype="float64")
        # nodata(-9999 등)를 명시해야 bilinear 보간이 유효셀과 nodata를 섞어 가짜
        # 고도/경사를 만들지 않는다. 미터치/원본 nodata 셀은 NaN으로 전파시킨다.
        reproject(
            source=rasterio.band(self.ds, 1),
            destination=dst,
            src_transform=self.ds.transform,
            src_crs=src_crs,
            dst_transform=transform,
            dst_crs=dst_crs,
            src_nodata=self.ds.nodata,
            dst_nodata=np.nan,
            init_dest_nodata=True,
            resampling=Resampling.bilinear,
        )
        xres = transform.a
        yres = -transform.e
        # dst에 이미 NaN이 들어 있으므로 nodata=None(== 비교 생략), gradient가 NaN 전파.
        slope, aspect = compute_slope_aspect(dst, abs(xres), abs(yres), nodata=None)
        self._slope, self._aspect = slope, aspect

        # 경사/향 샘플링용 인메모리 데이터셋
        memfile = rasterio.io.MemoryFile()
        prof = {
            "driver": "GTiff", "height": h, "width": w, "count": 1,
            "dtype": "float64", "crs": dst_crs, "transform": transform,
            "nodata": self.ds.nodata,
        }
        self._slope_mem = memfile  # 참조 유지
        self._slope_ds = memfile.open(**prof)
        # 데이터는 안 쓰고 좌표계/transform/bounds 만 사용 (인덱싱 용도)

    def query(self, lon: float, lat: float, point_crs: str = CRS_WGS84) -> TerrainQuery:
        # 고도 (원본 DEM에서)
        try:
            elev = sample_raster(self.ds, lon, lat, point_crs=point_crs,
                                 array=self._elev, method="bilinear")
        except RasterSampleError as e:
            return TerrainQuery(found=False, reason=str(e))

        # 경사/향
        self._ensure_slope_aspect()
        slope = aspect = None
        try:
            slope = sample_raster(self._slope_ds, lon, lat, point_crs=point_crs,
                                  array=self._slope, method="nearest")
            aspect = sample_raster(self._slope_ds, lon, lat, point_crs=point_crs,
                                   array=self._aspect, method="nearest")
        except RasterSampleError:
            slope = aspect = None

        return TerrainQuery(
            found=True,
            elevation_m=float(elev),
            slope_deg=float(slope) if slope is not None else None,
            aspect_deg=float(aspect) if aspect is not None else None,
            aspect_dir=aspect_to_direction(aspect) if aspect is not None else "평지",
        )
