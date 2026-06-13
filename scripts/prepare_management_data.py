"""Prepare lightweight forest management history layers for the app.

Inputs are national Forestry Service files. Outputs keep only Gangwon records
and only the fields needed for app explanation and SDM experiments.
"""
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

import pandas as pd


GANGWON_NAMES = {"강원도", "강원특별자치도"}
GANGWON_LAW_PREFIXES = ("42", "51")
TARGET_CRS = "EPSG:5179"
PEST_SOURCE_CRS = "EPSG:5186"


def _fix_mojibake(value):
    if not isinstance(value, str):
        return value
    try:
        return value.encode("latin1").decode("cp949")
    except Exception:
        return value


def _fix_frame_text(g):
    g = g.rename(columns={c: _fix_mojibake(c) for c in g.columns})
    for col in g.columns:
        if col == "geometry":
            continue
        if pd.api.types.is_object_dtype(g[col]) or pd.api.types.is_string_dtype(g[col]):
            g[col] = g[col].map(_fix_mojibake)
    return g


def _zip_shp_path(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        shp = next(n for n in zf.namelist() if n.lower().endswith(".shp"))
    return f"zip://{zip_path}!{shp}"


def _write_gpkg(g, out: Path, layer: str):
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    g.to_file(out, layer=layer, driver="GPKG")


def _prepare_activity(zip_path: Path, out: Path, layer: str, kind: str, tolerance: float):
    import geopandas as gpd

    print(f"[{kind}] reading {zip_path}", flush=True)
    g = gpd.read_file(_zip_shp_path(zip_path))
    g = _fix_frame_text(g)
    source_rows = int(len(g))
    if "시도" in g.columns:
        g = g[g["시도"].isin(GANGWON_NAMES)].copy()
    g = g.to_crs(TARGET_CRS)
    if tolerance > 0:
        g["geometry"] = g.geometry.simplify(tolerance, preserve_topology=True)
    g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()

    if kind == "planting":
        keep = [
            "UID", "사업년도", "시작일자", "종료일자", "사업명", "기관명",
            "시도", "시군구", "읍면동", "조림수종", "식재본수", "조성면적",
        ]
        numeric_cols = ["사업년도", "식재본수", "조성면적"]
    else:
        keep = [
            "UID", "사업년도", "시작일자", "종료일자", "사업명", "기관명",
            "작업종", "시도", "시군구", "읍면동", "작업면적",
        ]
        numeric_cols = ["사업년도", "작업면적"]

    for col in keep:
        if col not in g.columns:
            g[col] = None
    g = g[keep + ["geometry"]]
    for col in numeric_cols:
        g[col] = pd.to_numeric(g[col], errors="coerce")

    _write_gpkg(g, out, layer)
    report = {
        "source": str(zip_path),
        "out": str(out),
        "kind": kind,
        "source_rows": source_rows,
        "gangwon_rows": int(len(g)),
        "columns": keep,
        "crs": TARGET_CRS,
        "bounds": [float(v) for v in g.total_bounds] if len(g) else None,
        "bytes": out.stat().st_size,
        "simplify_tolerance_m": tolerance,
    }
    return report


def _prepare_disease(zip_path: Path, out: Path, layer: str, chunksize: int):
    import geopandas as gpd
    from shapely.geometry import Point

    print(f"[disease] reading {zip_path}", flush=True)
    frames = []
    source_rows = 0
    kept_rows = 0
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        for name in names:
            print(f"[disease] scanning {name}", flush=True)
            with zf.open(name) as f:
                reader = pd.read_csv(f, encoding="cp949", chunksize=chunksize)
                for chunk in reader:
                    source_rows += len(chunk)
                    law = chunk.get("법정동코드")
                    if law is None:
                        continue
                    law_s = law.astype("string").str.replace(r"\.0$", "", regex=True)
                    mask = law_s.str.startswith(GANGWON_LAW_PREFIXES, na=False)
                    sub = chunk.loc[mask].copy()
                    if sub.empty:
                        continue
                    sub["law_code"] = law_s.loc[mask].values
                    sub["x"] = pd.to_numeric(sub["지역X좌표"], errors="coerce")
                    sub["y"] = pd.to_numeric(sub["지역Y좌표"], errors="coerce")
                    sub = sub.dropna(subset=["x", "y"])
                    if sub.empty:
                        continue
                    sub["year"] = pd.to_datetime(
                        sub["조사일자"], errors="coerce"
                    ).dt.year
                    sub["diameter"] = pd.to_numeric(sub.get("발생경급수치"), errors="coerce")
                    sub["is_infected"] = sub.get("감염목구분").astype("string").eq("감염목").astype(int)
                    sub["is_control_done"] = sub.get("방제완료여부").astype("string").eq("완료").astype(int)
                    keep = [
                        "law_code", "year", "조사일자", "diameter",
                        "고사목구분", "감염목구분", "방제완료여부",
                        "is_infected", "is_control_done", "x", "y",
                    ]
                    sub = sub[keep]
                    frames.append(sub)
                    kept_rows += len(sub)

    if frames:
        df = pd.concat(frames, ignore_index=True)
        geom = [Point(x, y) for x, y in zip(df["x"], df["y"])]
        g = gpd.GeoDataFrame(df.drop(columns=["x", "y"]), geometry=geom, crs=PEST_SOURCE_CRS)
        g = g.to_crs(TARGET_CRS)
    else:
        g = gpd.GeoDataFrame(
            columns=[
                "law_code", "year", "조사일자", "diameter", "고사목구분",
                "감염목구분", "방제완료여부", "is_infected", "is_control_done", "geometry",
            ],
            geometry="geometry",
            crs=TARGET_CRS,
        )

    _write_gpkg(g, out, layer)
    report = {
        "source": str(zip_path),
        "out": str(out),
        "kind": "disease",
        "source_rows": int(source_rows),
        "gangwon_rows": int(kept_rows),
        "columns": [c for c in g.columns if c != "geometry"],
        "source_crs": PEST_SOURCE_CRS,
        "crs": TARGET_CRS,
        "bounds": [float(v) for v in g.total_bounds] if len(g) else None,
        "bytes": out.stat().st_size,
    }
    return report


def _prepare_survival(csv_path: Path, out: Path):
    df = pd.read_csv(csv_path, encoding="cp949")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return {
        "source": str(csv_path),
        "out": str(out),
        "kind": "survival_rate_timeseries",
        "rows": int(len(df)),
        "columns": list(df.columns),
        "bytes": out.stat().st_size,
        "note": "National annual survival-rate table. Useful for explanation, but not spatial enough for point-level SDM.",
    }


def _prepare_survey(csv_path: Path, out: Path):
    df = pd.read_csv(csv_path, encoding="cp949")
    keep = [
        "경영계획부번호", "방위", "경사도", "토성", "유효토심",
        "건습도", "지위", "지리", "임종", "임상", "소밀도", "우세목 임령",
    ]
    df = df[[c for c in keep if c in df.columns]].copy()
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return {
        "source": str(csv_path),
        "out": str(out),
        "kind": "forest_survey_table",
        "rows": int(len(df)),
        "unique_management_ids": int(df["경영계획부번호"].nunique()) if "경영계획부번호" in df else None,
        "columns": list(df.columns),
        "bytes": out.stat().st_size,
        "note": "High-value age/site table, but current lightweight forest map has no management-id column for spatial join.",
    }


def main() -> None:
    repo = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", default=r"C:\Users\Lee\Desktop\경진대회")
    ap.add_argument("--out-dir", default=str(repo / "data"))
    ap.add_argument("--chunksize", type=int, default=200000)
    args = ap.parse_args()

    source = Path(args.source_dir)
    out_dir = Path(args.out_dir)
    reports = {}
    reports["planting"] = _prepare_activity(
        source / "산림청_산림경영활동_조림공간정보_20171231.zip",
        out_dir / "gangwon_planting_light.gpkg",
        "planting",
        "planting",
        tolerance=3.0,
    )
    reports["tending"] = _prepare_activity(
        source / "산림청_산림경영활동_숲가꾸기공간정보_20171231.zip",
        out_dir / "gangwon_tending_light.gpkg",
        "tending",
        "tending",
        tolerance=3.0,
    )
    reports["disease"] = _prepare_disease(
        source / "산림청_산림병해충방제 병해충발생관리정보_20250902.zip",
        out_dir / "gangwon_disease_points_light.gpkg",
        "disease",
        chunksize=args.chunksize,
    )
    reports["survival"] = _prepare_survival(
        source / "산림청_조림 활착률 시계열 데이터_20241231.csv",
        out_dir / "derived" / "planting_survival_rates.csv",
    )
    reports["survey"] = _prepare_survey(
        source / "산림청_국유림경영정보_산림조사_20240829.csv",
        out_dir / "derived" / "national_forest_survey_light.parquet",
    )

    report_path = out_dir / "derived" / "management_data_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)
    print(json.dumps(reports, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
