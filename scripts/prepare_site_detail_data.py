"""
Prepare lightweight detailed forest-site/soil map from TB_FGDI_FS_IJ100.

This keeps environmental/site attributes only. Species-code, tree-height, and
site-index-like columns are intentionally excluded from app ML features because
they can leak the answer too directly.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

KEEP_COLUMNS = [
    "CTPRV_CD", "SGNG_CD", "EMNDN_CD", "SLTP_CD", "STQLT_CD",
    "RHGLT_GGRP", "WTHR_CD", "TPGRP_TPCD", "CLZN_CD", "PRRCK_LARG",
    "SOIL_DRNGE", "LOCTN_GRDN", "ALTTD_CD", "ACCMA_FOR", "WASH_CD",
    "SLANT_TYP", "EIGHT_CD", "ROCK_EXDGR", "RIDGE_VS", "WIND_EXDGR",
    "WTEFF_DGR", "VLDTY_SLDP",
    "SIAFLR_STP", "SIBFLR_STP", "SIAFLR_SLD", "SIBFLR_SLD",
    "SIAFLR_ERC", "SIBFLR_ERC", "SIAFLR_ORM", "SIBFLR_ORM",
    "SIAFLR_SCS", "SIBFLR_SCS", "SIAFLR_CBS", "SIBFLR_CBS",
    "SIAFLR_STR", "SIBFLR_STR", "SIAFLR_HGD", "SIBFLR_HGD",
    "SIAFLR_CNS", "SIBFLR_CNS", "SIAFLR_SMA", "SIBFLR_SMA",
    "SIAFLR_HYP", "SIBFLR_HYP", "SIAFLR_HER", "SIBFLR_HER",
    "SIAFLR_MDD", "SIBFLR_MDD", "SIAFLR_LAR", "SIBFLR_LAR",
]

NUMERIC_COLUMNS = ["LOCTN_GRDN", "VLDTY_SLDP", "SIAFLR_SLD", "SIBFLR_SLD"]

LABELS = {
    "SLTP_CD": "토양형코드",
    "STQLT_CD": "토양질코드",
    "RHGLT_GGRP": "기복군코드",
    "WTHR_CD": "풍화코드",
    "TPGRP_TPCD": "지형군코드",
    "CLZN_CD": "기후대코드",
    "PRRCK_LARG": "모암_대분류",
    "SOIL_DRNGE": "토양배수코드",
    "LOCTN_GRDN": "입지경사",
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


def main() -> None:
    import geopandas as gpd

    repo = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(repo / "data" / "incoming_tb_raw" / "TB_FGDI_FS_IJ100.shp"))
    ap.add_argument("--out", default=str(repo / "data" / "gangwon_site_detail_light.gpkg"))
    ap.add_argument("--layer", default="site_detail")
    ap.add_argument("--tolerance", type=float, default=5.0)
    args = ap.parse_args()

    raw = Path(args.raw)
    out = Path(args.out)
    print(f"[site-detail] reading {raw}", flush=True)
    g = gpd.read_file(raw, columns=KEEP_COLUMNS)
    missing = [c for c in KEEP_COLUMNS if c not in g.columns]
    for col in missing:
        g[col] = None
    g = g[KEEP_COLUMNS + ["geometry"]]
    g = g.to_crs("EPSG:5179")
    if args.tolerance > 0:
        g["geometry"] = g.geometry.simplify(args.tolerance, preserve_topology=True)
    g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()
    for col in NUMERIC_COLUMNS:
        g[col] = g[col].astype("float64", errors="ignore")

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    print(f"[site-detail] writing {out}", flush=True)
    g.to_file(out, layer=args.layer, driver="GPKG")

    report = {
        "source": str(raw),
        "out": str(out),
        "layer": args.layer,
        "rows": int(len(g)),
        "crs": str(g.crs),
        "bounds": [float(v) for v in g.total_bounds],
        "columns": KEEP_COLUMNS,
        "labels": LABELS,
        "excluded_for_leakage_risk": [
            "KOFTR_CD", "TREEHT1-5", "FRAG1-5", "REAL_STIND", "STQGD_VAL",
            "LARCH_STIN", "KRPN_STIND", "GNGN_LCLT", "CNDST_PINE",
            "ACTSM_STIN", "JBLPN_STIN",
        ],
        "simplify_tolerance_m": args.tolerance,
        "bytes": out.stat().st_size,
    }
    report_path = out.with_name(out.stem + "_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
