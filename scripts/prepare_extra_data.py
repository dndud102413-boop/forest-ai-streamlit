r"""
prepare_extra_data.py — 신규 공공데이터 3종 경량화 (데스크탑 전용)

원본 zip(사용자 다운로드 폴더)을 GDAL 가상경로(/vsizip)로 직접 읽어, 필요한 컬럼만
남기고 단순화해 경량 산출물을 FOREST_RECO_DATA_DIR(기본 wooyoung\data)에 만든다.
원본은 건드리지 않으므로 추가 디스크 부담이 거의 없다.

  - 산림기능구분도  -> gangwon_function_light.gpkg     (주기능 PF + 6개 점수 + 절대지역 A)
  - 맞춤형조림지도   -> gangwon_afforestation_light.gpkg(대표/유사/추가 수종 + 기후대)
  - 산사태위험지도   -> gangwon_landslide.tif           (위험등급 1~5, 타일 압축 = window read)
"""
from __future__ import annotations
import os
from pathlib import Path

import geopandas as gpd
import pyogrio
import rasterio

ZIP_DIR = os.environ.get("FOREST_EXTRA_ZIP_DIR", r"C:\Users\Lee\Desktop\경진대회")
OUT = Path(os.environ.get("FOREST_RECO_DATA_DIR",
                          r"C:\Users\Lee\Desktop\경진대회_shim\wooyoung\data"))
OUT.mkdir(parents=True, exist_ok=True)
SIMPLIFY_M = 30.0


def vz(zipname: str, inner: str) -> str:
    return f"/vsizip/{Path(ZIP_DIR).as_posix()}/{zipname}/{inner}"


def mb(p: Path) -> str:
    return f"{p.stat().st_size / 1024 / 1024:.1f} MB" if p.exists() else "-"


def light_vector(label, zipname, inner, columns, out_name):
    src = vz(zipname, inner)
    print(f"\n[{label}] reading {len(columns)} cols from {zipname} ...")
    g = pyogrio.read_dataframe(src, columns=columns, encoding="cp949")
    n0 = len(g)
    g = g[~g.geometry.is_empty & g.geometry.notna()]
    g["geometry"] = g.geometry.simplify(SIMPLIFY_M, preserve_topology=True)
    out = OUT / out_name
    if out.exists():
        out.unlink()
    g.to_file(out, driver="GPKG")
    print(f"   features {n0} -> {len(g)} | cols {list(g.columns)} | CRS {g.crs.to_string() if g.crs else '?'}")
    print(f"   wrote {out.name}  ({mb(out)})")


def light_raster(label, zipname, inner, out_name):
    src = vz(zipname, inner)
    print(f"\n[{label}] reading raster from {zipname} ...")
    with rasterio.open(src) as ds:
        prof = ds.profile.copy()
        prof.update(driver="GTiff", compress="deflate", predictor=2,
                    tiled=True, blockxsize=256, blockysize=256)
        arr = ds.read(1)
        out = OUT / out_name
        with rasterio.open(out, "w", **prof) as dst:
            dst.write(arr, 1)
        print(f"   {ds.width}x{ds.height} {ds.dtypes[0]} nodata={ds.nodata} CRS={ds.crs}")
    print(f"   wrote {out.name}  ({mb(out)})")


if __name__ == "__main__":
    light_vector("산림기능구분도", "산림기능구분도(일반인).zip", "51.shp",
                 ["PF", "WRCF", "FDMF", "EECF", "FRCF", "RHF", "UEF", "A"],
                 "gangwon_function_light.gpkg")
    light_vector("맞춤형조림지도", "맞춤형조림지도.zip", "51.shp",
                 ["CLZN_CD", "RPRSN_KOFT", "KOFTR_LIST", "S_LRT_KOFT", "ADDTN_KOFT", "KOFTR_NM"],
                 "gangwon_afforestation_light.gpkg")
    light_raster("산사태위험지도", "산사태위험지도.zip", "51.tif",
                 "gangwon_landslide.tif")
    print("\nPREPARE_EXTRA_DONE")
