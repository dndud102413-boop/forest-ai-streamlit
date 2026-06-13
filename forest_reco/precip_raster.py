"""precip_raster.py — 2020~2024 강수량 격자 조회."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .config import SETTINGS, CRS_WGS84
from .geo import sample_raster, RasterSampleError


BAND_LABELS = {
    1: "annual_mean_mm",
    2: "growing_may_sep_mm",
    3: "summer_jun_aug_mm",
    4: "winter_dec_feb_mm",
}


class PrecipRaster:
    def __init__(self, dataset, settings=SETTINGS):
        self.ds = dataset
        self.settings = settings
        self._arrays = {i: dataset.read(i) for i in BAND_LABELS}

    @classmethod
    def load(cls, path: Optional[Path] = None, settings=SETTINGS) -> Optional["PrecipRaster"]:
        import rasterio

        p = Path(path or settings.precip_path)
        if not p.exists():
            return None
        return cls(rasterio.open(p), settings=settings)

    def query(self, lon: float, lat: float, point_crs: str = CRS_WGS84) -> Optional[dict]:
        out = {}
        found = False
        for band, label in BAND_LABELS.items():
            try:
                v = sample_raster(self.ds, lon, lat, point_crs=point_crs,
                                  array=self._arrays[band], method="nearest")
                if v is not None and float(v) != self.ds.nodata:
                    out[label] = float(v)
                    found = True
                else:
                    out[label] = None
            except RasterSampleError:
                out[label] = None
        return out if found else None
