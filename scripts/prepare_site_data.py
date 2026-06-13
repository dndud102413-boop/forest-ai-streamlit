"""
Prepare lightweight forest-site map data from DATA015 산림입지도 shapefiles.

The raw 51_*.shp files are several GB. This script keeps the useful site/soil
attributes, normalizes the CRS to EPSG:5179, simplifies geometries, and writes a
single lightweight GeoPackage for the app and future SDM experiments.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

KEEP_COLUMNS = [
    "MPDMR_NO",
    "PRRCK_LARG", "PRRCK_MDDL",
    "LOCTN_ALTT", "LOCTN_GRDN", "EIGHT_AGL",
    "CLZN_CD", "TPGRP_TPCD", "PRDN_FOM_C",
    "SLANT_TYP", "SLDPT_TPCD", "SCSTX_CD", "SLTP_CD",
    "LDMARK_STN", "MAP_LABEL",
]

LABELS = {
    "MPDMR_NO": "도엽번호",
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

NUMERIC_COLUMNS = ["LOCTN_ALTT", "LOCTN_GRDN", "EIGHT_AGL"]


def main() -> None:
    import geopandas as gpd

    repo = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default=str(repo / "data" / "incoming_51_raw"))
    ap.add_argument("--out", default=str(repo / "data" / "gangwon_site_light.gpkg"))
    ap.add_argument("--layer", default="site")
    ap.add_argument("--tolerance", type=float, default=3.0,
                    help="Geometry simplification tolerance in meters.")
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    out = Path(args.out)
    shp_paths = sorted(raw_dir.glob("51_*.shp"))
    if not shp_paths:
        raise FileNotFoundError(f"No 51_*.shp files found in {raw_dir}")

    frames = []
    source_reports = []
    for shp in shp_paths:
        print(f"[site] reading {shp.name}", flush=True)
        g = gpd.read_file(shp, columns=KEEP_COLUMNS)
        source_reports.append({
            "source": shp.name,
            "rows": int(len(g)),
            "crs": str(g.crs),
            "bounds": [float(v) for v in g.total_bounds],
        })
        missing = [c for c in KEEP_COLUMNS if c not in g.columns]
        for col in missing:
            g[col] = None
        g = g[KEEP_COLUMNS + ["geometry"]]
        if g.crs is None:
            raise ValueError(f"{shp.name} has no CRS")
        g = g.to_crs("EPSG:5179")
        if args.tolerance > 0:
            g["geometry"] = g.geometry.simplify(args.tolerance, preserve_topology=True)
        g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()
        frames.append(g)

    merged = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True),
                              geometry="geometry", crs="EPSG:5179")
    for col in NUMERIC_COLUMNS:
        merged[col] = pd.to_numeric(merged[col], errors="coerce")

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    print(f"[site] writing {out}", flush=True)
    merged.to_file(out, layer=args.layer, driver="GPKG")

    report = {
        "out": str(out),
        "layer": args.layer,
        "rows": int(len(merged)),
        "crs": str(merged.crs),
        "bounds": [float(v) for v in merged.total_bounds],
        "source_reports": source_reports,
        "columns": KEEP_COLUMNS,
        "labels": LABELS,
        "simplify_tolerance_m": args.tolerance,
        "bytes": out.stat().st_size,
    }
    report_path = out.with_name(out.stem + "_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
