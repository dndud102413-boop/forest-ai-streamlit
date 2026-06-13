"""
prepare_data.py — 원천 데이터 정비 유틸 (노트북의 산재한 셀들을 1개 스크립트로)

기능:
  merge-dem   : 여러 DEM .tif 타일을 1개로 병합
  clip        : 임상도(shp)/DEM(tif)를 관심영역(bbox)으로 잘라 경량화
  light-gpkg  : 임상도(shp)를 컬럼축소+단순화하여 경량 GeoPackage로 변환(메모리 안전, 배치)
  inspect     : 임상도/DEM 메타(좌표계, 범위, 컬럼, 고유값) 점검

사용:
  python scripts/prepare_data.py merge-dem  --in "../*.tif" --out data/gangwon_dem.tif
  python scripts/prepare_data.py light-gpkg --shp data/51_1.shp data/51_2.shp \
        --out data/gangwon_forest_light.gpkg --tolerance 30
  python scripts/prepare_data.py clip --shp data/51_1.shp data/51_2.shp --dem data/gangwon_dem.tif \
        --bbox 127.0 37.0 129.5 38.7 --out-dir data_small
  python scripts/prepare_data.py inspect --shp data/51_1.shp --dem data/gangwon_dem.tif

forest_reco는 data_dir에 gangwon_forest_light.gpkg가 있으면 자동으로 우선 사용한다
(config.prefer_light_gpkg). 원본 임상도(약 2GB)는 light-gpkg로 ~170MB까지 줄어든다.
"""
from __future__ import annotations

import argparse
import glob
from pathlib import Path


def merge_dem(patterns: list[str], out: str):
    import rasterio
    from rasterio.merge import merge

    files = []
    for p in patterns:
        files.extend(sorted(glob.glob(p)))
    files = [f for f in files if Path(f).name != Path(out).name]
    if not files:
        raise SystemExit(f"입력 tif를 찾지 못함: {patterns}")
    print(f"병합 대상 {len(files)}개:")
    for f in files:
        print("  ", f)
    srcs = [rasterio.open(f) for f in files]
    mosaic, transform = merge(srcs)
    meta = srcs[0].meta.copy()
    meta.update(driver="GTiff", height=mosaic.shape[1], width=mosaic.shape[2],
                transform=transform, count=mosaic.shape[0])
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", **meta) as dst:
        dst.write(mosaic)
    for s in srcs:
        s.close()
    print("DEM 병합 완료:", out, "CRS:", meta.get("crs"))


def clip(shp_paths: list[str], dem_path: str | None, bbox: list[float], out_dir: str):
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import box

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    bbox_gdf = gpd.GeoDataFrame(geometry=[box(*bbox)], crs="EPSG:4326")

    if shp_paths:
        frames = [gpd.read_file(p) for p in shp_paths]
        crs0 = frames[0].crs
        forest = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True),
                                  geometry="geometry", crs=crs0)
        bb = bbox_gdf.to_crs(crs0).geometry.iloc[0]
        small = forest[forest.intersects(bb)].copy()
        op = out / "forest_small.shp"
        small.to_file(op, encoding="utf-8")
        print(f"임상도 경량화: {forest.shape[0]} → {small.shape[0]} 폴리곤 → {op}")

    if dem_path:
        import rasterio
        from rasterio.mask import mask
        with rasterio.open(dem_path) as src:
            geoms = [g for g in bbox_gdf.to_crs(src.crs).geometry]
            img, tr = mask(src, geoms, crop=True)
            meta = src.meta.copy()
            meta.update(driver="GTiff", height=img.shape[1], width=img.shape[2], transform=tr)
            op = out / "dem_small.tif"
            with rasterio.open(op, "w", **meta) as dst:
                dst.write(img)
        print("DEM 경량화 →", op)


_LIGHT_COLS = ["FRTP_NM", "KOFTR_NM", "DMCLS_NM", "AGCLS_NM", "DNST_NM"]


def light_gpkg(shp_paths: list[str], out: str, tolerance: float,
               bbox: list[float], batch: int):
    """임상도 .shp → 경량 GeoPackage.

    원본이 커서(각 ~1GB) 한 번에 다 읽으면 RAM이 부족할 수 있으므로 pyogrio로 일정
    개수씩(batch) 읽어 컬럼축소·단순화·bbox crop 후 gpkg에 이어붙인다(append).
    """
    import geopandas as gpd
    import pyogrio
    from pyproj import Transformer

    srcs = [s for s in shp_paths if Path(s).exists()]
    if not srcs:
        raise SystemExit(f"입력 임상도를 찾지 못함: {shp_paths}")
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()  # append 누적 방지

    written = 0
    crop_box = None
    for src in srcs:
        info = pyogrio.read_info(src)
        n, crs = info["features"], info["crs"]
        cols = [c for c in _LIGHT_COLS if c in list(info["fields"])]
        print(f"[light-gpkg] {Path(src).name}: features={n:,} CRS={crs} 유지컬럼={cols}")
        if crop_box is None:
            tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
            pts = [tr.transform(lon, lat)
                   for lon in (bbox[0], bbox[2]) for lat in (bbox[1], bbox[3])]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            crop_box = (min(xs), min(ys), max(xs), max(ys))

        for start in range(0, n, batch):
            gdf = gpd.read_file(src, columns=cols, engine="pyogrio",
                                skip_features=start, max_features=batch)
            if gdf.empty:
                continue
            gdf = gdf.cx[crop_box[0]:crop_box[2], crop_box[1]:crop_box[3]]
            if gdf.empty:
                continue
            gdf["geometry"] = gdf.geometry.simplify(tolerance, preserve_topology=True)
            gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
            if gdf.empty:
                continue
            gdf.to_file(out_path, driver="GPKG", engine="pyogrio",
                        mode=("w" if written == 0 else "a"))
            written += len(gdf)
            print(f"    누적 {written:,}건")

    size_mb = out_path.stat().st_size / 1024 / 1024 if out_path.exists() else 0
    print(f"[light-gpkg] 저장 완료: {out_path}  ({size_mb:.1f} MB, {written:,} 폴리곤, "
          f"tolerance={tolerance})")


def inspect(shp_path: str | None, dem_path: str | None):
    if shp_path:
        import geopandas as gpd
        g = gpd.read_file(shp_path)
        print(f"\n[임상도] {shp_path}")
        print("  CRS:", g.crs, "| 폴리곤:", len(g))
        print("  컬럼:", g.columns.tolist())
        for c in ("FRTP_NM", "KOFTR_NM", "DMCLS_NM", "AGCLS_NM", "DNST_NM"):
            if c in g.columns:
                vals = g[c].dropna().unique()[:12]
                print(f"  {c} 고유값(일부): {list(vals)}")
    if dem_path:
        import rasterio
        with rasterio.open(dem_path) as d:
            print(f"\n[DEM] {dem_path}")
            print("  CRS:", d.crs, "| 크기:", d.width, "x", d.height,
                  "| 밴드:", d.count, "| nodata:", d.nodata)
            print("  범위:", d.bounds, "| 해상도:", d.res)


def main():
    ap = argparse.ArgumentParser(description="산림 데이터 정비 유틸")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("merge-dem")
    m.add_argument("--in", dest="inp", nargs="+", required=True)
    m.add_argument("--out", required=True)

    c = sub.add_parser("clip")
    c.add_argument("--shp", nargs="*", default=[])
    c.add_argument("--dem", default=None)
    c.add_argument("--bbox", nargs=4, type=float, required=True,
                   metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"))
    c.add_argument("--out-dir", required=True)

    lg = sub.add_parser("light-gpkg")
    lg.add_argument("--shp", nargs="+", required=True)
    lg.add_argument("--out", required=True)
    lg.add_argument("--tolerance", type=float, default=30.0)
    lg.add_argument("--bbox", nargs=4, type=float, default=[127.0, 37.0, 129.5, 38.7],
                    metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"))
    lg.add_argument("--batch", type=int, default=150000)

    i = sub.add_parser("inspect")
    i.add_argument("--shp", default=None)
    i.add_argument("--dem", default=None)

    a = ap.parse_args()
    if a.cmd == "merge-dem":
        merge_dem(a.inp, a.out)
    elif a.cmd == "clip":
        clip(a.shp, a.dem, a.bbox, a.out_dir)
    elif a.cmd == "light-gpkg":
        light_gpkg(a.shp, a.out, a.tolerance, a.bbox, a.batch)
    elif a.cmd == "inspect":
        inspect(a.shp, a.dem)


if __name__ == "__main__":
    main()
