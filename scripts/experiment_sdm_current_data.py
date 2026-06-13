"""
Run SDM experiments with the currently available data only.

This script compares model families, class counts, sampling sizes, and a small
set of engineered environmental features. It intentionally avoids forest-map
attributes that would leak the answer label too directly.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path

import numpy as np

from forest_reco.config import CRS_WGS84
from forest_reco.pipeline import DataSources
from forest_reco.sdm import _DEFAULT_SDM_EXCLUDE, _aspect_components


BASE_FEATURES = [
    "elevation", "slope", "aspect_sin", "aspect_cos",
    "lat", "lon", "temp_obs", "precip_obs",
]

ENGINEERED_FEATURES = BASE_FEATURES + [
    "elevation2", "slope2", "lat_lon", "temp_precip_ratio",
]


def _num(v) -> float:
    try:
        return float(v) if v is not None else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _row_features(base: list[float], feature_set: str) -> list[float]:
    if feature_set == "base":
        return base
    elevation, slope, aspect_sin, aspect_cos, lat, lon, temp, precip = base
    ratio = precip / (temp + 20.0) if not math.isnan(precip) and not math.isnan(temp) else float("nan")
    return base + [
        elevation * elevation,
        slope * slope,
        lat * lon,
        ratio,
    ]


def build_dataset(sources: DataSources, top_species: int, n_samples: int, random_state: int):
    import geopandas as gpd

    gdf = sources.forest.gdf
    work = gdf[["geometry", "KOFTR_NM"]].copy()
    work["KOFTR_NM"] = work["KOFTR_NM"].astype(str)
    work = work[~work["KOFTR_NM"].isin(_DEFAULT_SDM_EXCLUDE)]

    top = work["KOFTR_NM"].value_counts().head(top_species).index
    work = work[work["KOFTR_NM"].isin(top)]
    n = min(n_samples, len(work))
    sample = work.sample(n=n, random_state=random_state)

    rep = sample.geometry.representative_point()
    rep_wgs = gpd.GeoSeries(rep, crs=work.crs).to_crs(CRS_WGS84)

    rows: list[list[float]] = []
    labels: list[str] = []
    for geom, label in zip(rep_wgs.values, sample["KOFTR_NM"].values):
        tq = sources.terrain.query(geom.x, geom.y, point_crs=CRS_WGS84)
        if not tq.found or tq.elevation_m is None:
            continue
        aspect_sin, aspect_cos = _aspect_components(tq.aspect_deg)
        oc = sources.observed.idw(geom.y, geom.x) if sources.observed else {}
        rows.append([
            _num(tq.elevation_m),
            _num(tq.slope_deg if tq.slope_deg is not None else 0.0),
            aspect_sin,
            aspect_cos,
            _num(geom.y),
            _num(geom.x),
            _num((oc or {}).get("temp_c")),
            _num((oc or {}).get("precip_mm")),
        ])
        labels.append(str(label))

    return np.array(rows, dtype="float64"), np.array(labels)


def make_estimator(model: str, random_state: int):
    if model == "hgb":
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.08, max_depth=None,
            l2_regularization=1.0, random_state=random_state)
    if model == "hgb_tuned":
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(
            max_iter=500, learning_rate=0.04, max_leaf_nodes=31,
            min_samples_leaf=15, l2_regularization=0.2, random_state=random_state)
    if model == "rf":
        from sklearn.ensemble import RandomForestClassifier
        return RandomForestClassifier(
            n_estimators=500, max_features="sqrt", class_weight="balanced",
            n_jobs=-1, random_state=random_state)
    if model == "extra":
        from sklearn.ensemble import ExtraTreesClassifier
        return ExtraTreesClassifier(
            n_estimators=500, max_features="sqrt", class_weight="balanced",
            n_jobs=-1, random_state=random_state)
    if model == "extra_deep":
        from sklearn.ensemble import ExtraTreesClassifier
        return ExtraTreesClassifier(
            n_estimators=700, max_features=None, min_samples_leaf=1,
            class_weight="balanced", n_jobs=-1, random_state=random_state)
    raise ValueError(model)


def evaluate(X, y, *, model: str, feature_set: str, use_weight: bool, random_state: int):
    from sklearn.metrics import accuracy_score, f1_score, top_k_accuracy_score
    from sklearn.model_selection import train_test_split
    from sklearn.utils.class_weight import compute_sample_weight

    Xf = np.array([_row_features(list(row), feature_set) for row in X], dtype="float64")
    Xtr, Xte, ytr, yte = train_test_split(
        Xf, y, test_size=0.2, random_state=random_state, stratify=y)
    clf = make_estimator(model, random_state)
    sample_weight = compute_sample_weight("balanced", ytr) if use_weight else None
    start = time.time()
    if sample_weight is not None and model.startswith("hgb"):
        clf.fit(Xtr, ytr, sample_weight=sample_weight)
    else:
        clf.fit(Xtr, ytr)
    elapsed = round(time.time() - start, 1)

    pred = clf.predict(Xte)
    proba = clf.predict_proba(Xte)
    labels = clf.classes_
    k = min(3, len(labels) - 1)
    top3 = top_k_accuracy_score(yte, proba, k=k, labels=labels) if k >= 1 else None
    return {
        "model": model,
        "feature_set": feature_set,
        "use_sample_weight": bool(use_weight),
        "accuracy": round(float(accuracy_score(yte, pred)), 3),
        "f1_macro": round(float(f1_score(yte, pred, average="macro")), 3),
        "f1_weighted": round(float(f1_score(yte, pred, average="weighted")), 3),
        "top3_accuracy": round(float(top3), 3) if top3 is not None else None,
        "fit_seconds": elapsed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="data/derived/sdm_experiments")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--max-samples", type=int, default=12000)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    out_dir = root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    sources = DataSources(use_mock=False)
    results = []
    datasets = {}
    top_values = [3, 4, 5, 6, 8, 10]
    sample_values = [4000, 8000, args.max_samples]
    models = ["hgb", "hgb_tuned", "rf", "extra", "extra_deep"]

    for top_species in top_values:
        for n_samples in sample_values:
            key = (top_species, n_samples)
            print(f"[dataset] top={top_species} n={n_samples}", flush=True)
            X, y = build_dataset(sources, top_species, n_samples, args.random_state)
            datasets[key] = (X, y)
            class_counts = {str(c): int((y == c).sum()) for c in sorted(set(y))}
            for feature_set in ["base", "engineered"]:
                for model in models:
                    weight_options = [True, False] if model.startswith("hgb") else [False]
                    for use_weight in weight_options:
                        try:
                            row = evaluate(
                                X, y, model=model, feature_set=feature_set,
                                use_weight=use_weight, random_state=args.random_state)
                            row.update({
                                "top_species": top_species,
                                "n_requested": n_samples,
                                "n_total": int(len(y)),
                                "n_classes": int(len(set(y))),
                                "classes": sorted(str(c) for c in set(y)),
                                "class_counts": class_counts,
                            })
                            results.append(row)
                            print(json.dumps(row, ensure_ascii=False), flush=True)
                        except Exception as exc:  # noqa: BLE001
                            print(f"[skip] {top_species=} {n_samples=} {feature_set=} {model=} {exc}", flush=True)

    results.sort(key=lambda r: (r["f1_macro"], r["top3_accuracy"] or 0, r["accuracy"]), reverse=True)
    json_path = out_dir / "results.json"
    csv_path = out_dir / "results.csv"
    summary_path = out_dir / "summary.json"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    keep = [
        "top_species", "n_requested", "n_total", "n_classes", "model", "feature_set",
        "use_sample_weight", "accuracy", "f1_macro", "f1_weighted",
        "top3_accuracy", "fit_seconds",
    ]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keep)
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k) for k in keep})

    summary = {
        "best_by_f1_macro": results[:10],
        "best_balanced": sorted(
            results,
            key=lambda r: (min(r["f1_macro"], r["top3_accuracy"] or 0), r["f1_macro"]),
            reverse=True,
        )[:10],
        "feature_names": {
            "base": BASE_FEATURES,
            "engineered": ENGINEERED_FEATURES,
        },
        "note": "These experiments use only current terrain, location, and observed-climate features. Forest stand attributes are excluded to avoid label leakage.",
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n[done]")
    print(f"summary: {summary_path}")
    print(f"csv: {csv_path}")


if __name__ == "__main__":
    main()
