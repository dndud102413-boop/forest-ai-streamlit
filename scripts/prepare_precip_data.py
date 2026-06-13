"""
Prepare lightweight precipitation raster from WorldClim/CRU monthly GeoTIFF zip.

Input: wc2.1_cruts4.09_2.5m_prec_2020-2024.zip
Output: data/gangwon_precip_2020_2024.tif

Bands:
  1 annual_mean_mm
  2 growing_may_sep_mm
  3 summer_jun_aug_mm
  4 winter_dec_feb_mm
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np


BAND_DESCRIPTIONS = [
    "annual_mean_mm",
    "growing_may_sep_mm",
    "summer_jun_aug_mm",
    "winter_dec_feb_mm",
]


def main() -> None:
    import rasterio
    from rasterio.windows import from_bounds

    repo = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", dest="zip_path", required=True)
    ap.add_argument("--out", default=str(repo / "data" / "gangwon_precip_2020_2024.tif"))
    # Slightly wider than the current Gangwon data extent.
    ap.add_argument("--bounds", nargs=4, type=float,
                    default=[127.0, 36.8, 129.6, 38.6],
                    metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"))
    args = ap.parse_args()

    zip_path = Path(args.zip_path)
    out = Path(args.out)
    monthly = []
    pat = re.compile(r"prec_(\d{4})-(\d{2})\.tif$")
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            m = pat.search(name)
            if m:
                monthly.append((int(m.group(1)), int(m.group(2)), name))
        monthly.sort()
        if not monthly:
            raise FileNotFoundError("No monthly precipitation tif files found in zip")

        sums_by_year: dict[int, np.ndarray] = {}
        growing_by_year: dict[int, np.ndarray] = {}
        summer_by_year: dict[int, np.ndarray] = {}
        winter_by_year: dict[int, np.ndarray] = {}
        counts = defaultdict(int)
        profile = None
        window = None
        transform = None

        for year, month, name in monthly:
            print(f"[precip] reading {name}", flush=True)
            with z.open(name) as f:
                data = f.read()
            with rasterio.MemoryFile(data) as mem:
                with mem.open() as src:
                    if window is None:
                        window = from_bounds(*args.bounds, transform=src.transform)
                        window = window.round_offsets().round_lengths()
                        transform = src.window_transform(window)
                        profile = src.profile.copy()
                        profile.update({
                            "height": int(window.height),
                            "width": int(window.width),
                            "count": len(BAND_DESCRIPTIONS),
                            "dtype": "float32",
                            "compress": "deflate",
                            "predictor": 2,
                            "transform": transform,
                            "nodata": -9999.0,
                        })
                    arr = src.read(1, window=window).astype("float32")
                    nodata = src.nodata
                    if nodata is not None:
                        arr = np.where(arr == nodata, np.nan, arr)
                    sums_by_year.setdefault(year, np.zeros_like(arr, dtype="float32"))
                    sums_by_year[year] += np.nan_to_num(arr, nan=0.0)
                    counts[(year, "annual")] += 1
                    if 5 <= month <= 9:
                        growing_by_year.setdefault(year, np.zeros_like(arr, dtype="float32"))
                        growing_by_year[year] += np.nan_to_num(arr, nan=0.0)
                        counts[(year, "growing")] += 1
                    if 6 <= month <= 8:
                        summer_by_year.setdefault(year, np.zeros_like(arr, dtype="float32"))
                        summer_by_year[year] += np.nan_to_num(arr, nan=0.0)
                        counts[(year, "summer")] += 1
                    if month in (12, 1, 2):
                        winter_by_year.setdefault(year, np.zeros_like(arr, dtype="float32"))
                        winter_by_year[year] += np.nan_to_num(arr, nan=0.0)
                        counts[(year, "winter")] += 1

    years = sorted(sums_by_year)
    annual = np.mean([sums_by_year[y] for y in years], axis=0)
    growing = np.mean([growing_by_year[y] for y in years if y in growing_by_year], axis=0)
    summer = np.mean([summer_by_year[y] for y in years if y in summer_by_year], axis=0)
    winter = np.mean([winter_by_year[y] for y in years if y in winter_by_year], axis=0)
    stack = np.stack([annual, growing, summer, winter]).astype("float32")
    stack = np.where(np.isfinite(stack), stack, -9999.0)

    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", **profile) as dst:
        for i, desc in enumerate(BAND_DESCRIPTIONS, start=1):
            dst.write(stack[i - 1], i)
            dst.set_band_description(i, desc)

    report = {
        "source": str(zip_path),
        "out": str(out),
        "bands": BAND_DESCRIPTIONS,
        "years": years,
        "bounds_wgs84": args.bounds,
        "shape": [int(stack.shape[1]), int(stack.shape[2])],
        "bytes": out.stat().st_size,
        "summary": {
            desc: {
                "min": float(np.nanmin(np.where(stack[i] == -9999.0, np.nan, stack[i]))),
                "mean": float(np.nanmean(np.where(stack[i] == -9999.0, np.nan, stack[i]))),
                "max": float(np.nanmax(np.where(stack[i] == -9999.0, np.nan, stack[i]))),
            }
            for i, desc in enumerate(BAND_DESCRIPTIONS)
        },
    }
    report_path = out.with_name(out.stem + "_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
