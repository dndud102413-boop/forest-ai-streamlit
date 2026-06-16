r"""
evaluate_models_cv.py — RF / HGB / RF+HGB 앙상블의 교차검증(CV) 사전 계산.

앱(streamlit)은 CV를 실행 중에 계산하지 않는다(안정성). 이 스크립트로 **미리** 계산해
JSON으로 저장하고, 앱은 그 결과 파일만 읽어 표에 표시한다.

두 가지 CV를 계산한다.
  1) Stratified K-Fold CV   — 수종 비율 유지 반복 검증(성능 안정성)
  2) Spatial Block CV       — lat/lon 블록 GroupKFold(공간 일반화)

지표: Accuracy / F1 macro / F1 weighted / Top-3 accuracy 의 fold 평균±표준편차,
      수종별 F1 평균·support, 합산 confusion matrix, fold별 상세.

실행:
    python scripts/evaluate_models_cv.py                 # 기본(샘플 5000, 5-fold)
    python scripts/evaluate_models_cv.py --samples 8000 --folds 5
환경변수 FOREST_RECO_DATA_DIR 가 데이터 폴더를 가리켜야 한다(.bat과 동일).
결과: <data_dir>/derived/model_eval_cv_results.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forest_reco.config import Settings  # noqa: E402
from forest_reco.pipeline import DataSources  # noqa: E402
from forest_reco.sdm import SpeciesDistributionModel, _make_estimator  # noqa: E402


def _top3(proba, yte, classes):
    """학습 클래스에 속한 표본만으로 Top-3 정확도."""
    from sklearn.metrics import top_k_accuracy_score
    yte = np.asarray(yte)
    mask = np.isin(yte, classes)
    k = min(3, len(classes) - 1)
    if not mask.any() or k < 1:
        return None
    try:
        return float(top_k_accuracy_score(yte[mask], proba[mask], k=k, labels=classes))
    except Exception:  # noqa: BLE001
        return None


def _fold_metrics(proba, yte, classes):
    from sklearn.metrics import accuracy_score, f1_score
    pred = np.array(classes)[np.argmax(proba, axis=1)]
    return {
        "accuracy": float(accuracy_score(yte, pred)),
        "f1_macro": float(f1_score(yte, pred, average="macro", zero_division=0)),
        "f1_weighted": float(f1_score(yte, pred, average="weighted", zero_division=0)),
        "top3_accuracy": _top3(proba, yte, classes),
    }, pred


def _agg(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None, None
    return round(float(np.mean(vals)), 3), round(float(np.std(vals)), 3)


def _run_cv(X, y, splitter, split_args, species, label):
    """한 CV 방식에서 RF/HGB/Ensemble fold별 지표 + (Stratified용) 누적 예측 반환."""
    from sklearn.utils.class_weight import compute_sample_weight
    from sklearn.metrics import f1_score, confusion_matrix

    per_model = {"RF": [], "HGB": [], "RF+HGB Ensemble": []}
    fold_rows = []
    cm_sum = np.zeros((len(species), len(species)), dtype=int)
    ens_true, ens_pred = [], []
    fold_no = 0
    for tr, te in splitter.split(X, y, *split_args):
        fold_no += 1
        Xtr, Xte, ytr, yte = X[tr], X[te], y[tr], y[te]
        if len(set(ytr)) < 2 or len(te) == 0:
            continue
        sw = compute_sample_weight("balanced", ytr)
        rf = _make_estimator("rf", 42)
        rf.fit(Xtr, ytr)
        classes = list(rf.classes_)
        rf_proba = rf.predict_proba(Xte)
        rfm, _ = _fold_metrics(rf_proba, yte, classes)
        per_model["RF"].append(rfm)
        row = {"fold": fold_no, "n_test": int(len(te)), "RF": rfm}
        try:
            hgb = _make_estimator("hgb", 42)
            hgb.fit(Xtr, ytr, sample_weight=sw)
            hgb_proba = hgb.predict_proba(Xte)   # rf와 동일 ytr → classes_ 동일 순서
            hgm, _ = _fold_metrics(hgb_proba, yte, classes)
            ens_proba = np.mean([rf_proba, hgb_proba], axis=0)
            enm, enp = _fold_metrics(ens_proba, yte, classes)
            per_model["HGB"].append(hgm)
            per_model["RF+HGB Ensemble"].append(enm)
            row["HGB"], row["RF+HGB Ensemble"] = hgm, enm
            ens_true.extend(list(yte))
            ens_pred.extend(list(enp))
            cm_sum += confusion_matrix(yte, enp, labels=species)
        except Exception as e:  # noqa: BLE001 - HGB fold 실패 시 RF만 집계
            row["error"] = f"HGB fold skipped: {type(e).__name__}"
        fold_rows.append(row)

    results = []
    n_folds_done = len(per_model["RF"])
    for model, folds in per_model.items():
        if not folds:
            continue
        am, asd = _agg([f["accuracy"] for f in folds])
        fmm, fms = _agg([f["f1_macro"] for f in folds])
        fwm, fws = _agg([f["f1_weighted"] for f in folds])
        tm, ts = _agg([f["top3_accuracy"] for f in folds])
        results.append({
            "model": model, "validation_type": label,
            "accuracy_mean": am, "accuracy_std": asd,
            "f1_macro_mean": fmm, "f1_macro_std": fms,
            "f1_weighted_mean": fwm, "f1_weighted_std": fws,
            "top3_accuracy_mean": tm, "top3_accuracy_std": ts,
            "n_folds": len(folds),
        })

    per_species = []
    if ens_true:
        f1s = f1_score(ens_true, ens_pred, labels=species, average=None, zero_division=0)
        _, sup = np.unique(np.asarray(ens_true), return_counts=True)
        sup_map = dict(zip(*np.unique(np.asarray(ens_true), return_counts=True)))
        for sp, f in zip(species, f1s):
            per_species.append({"species": sp, "f1_mean": round(float(f), 3),
                                "support": int(sup_map.get(sp, 0))})
    return results, fold_rows, cm_sum.tolist(), per_species, n_folds_done


def _spatial_groups(X, block_deg=0.1):
    lat = np.floor(X[:, 4] / block_deg).astype(np.int64)
    lon = np.floor(X[:, 5] / block_deg).astype(np.int64)
    return lat * 100000 + lon


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=5000, help="CV 표본 수(속도 조절)")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()

    s = Settings.from_env()
    s.light_mode = False  # CV는 데스크탑 풀데이터 기준
    src = DataSources(settings=s, use_mock=False)
    top_species = getattr(s, "sdm_top_species", 5) or 5
    print(f"[CV] 표본 생성 중 (samples={args.samples}, top_species={top_species}) ...")
    X, y, feat = SpeciesDistributionModel._build_xy(
        src.forest, src.terrain, args.samples, 15, 42, None, top_species,
        src.observed, src.site, src.precip, None, None)
    species = sorted(set(y.tolist()))
    print(f"[CV] X={X.shape}, 수종 {len(species)}개: {species}")

    from sklearn.model_selection import StratifiedKFold, GroupKFold
    all_results, fold_details = [], {}

    print(f"[CV] Stratified {args.folds}-Fold ...")
    skf = StratifiedKFold(n_splits=args.folds, shuffle=True, random_state=42)
    r1, fr1, cm1, ps1, nf1 = _run_cv(X, y, skf, (), species, f"Stratified {args.folds}-Fold CV")
    all_results += r1
    fold_details["stratified"] = fr1

    print(f"[CV] Spatial Block {args.folds}-Fold ...")
    groups = _spatial_groups(X)
    spatial_per_species, cm2 = [], None
    if len(set(groups.tolist())) >= args.folds:
        gkf = GroupKFold(n_splits=args.folds)
        r2, fr2, cm2, ps2, nf2 = _run_cv(X, y, gkf, (groups,), species, "Spatial Block CV")
        all_results += r2
        fold_details["spatial_block"] = fr2
        spatial_per_species = ps2
    else:
        print("[CV] 공간 블록이 부족해 Spatial Block CV를 건너뜁니다.")

    out = {
        "created_at": "2026-06-16",
        "target_species": species,
        "n_samples": int(len(X)),
        "n_species": len(species),
        "n_features": len(feat),
        "features": feat,
        "results": all_results,
        "per_species_f1": ps1,                      # Stratified CV 앙상블 기준
        "per_species_f1_spatial": spatial_per_species,
        "confusion_stratified": {"labels": species, "matrix": cm1},
        "confusion_spatial": ({"labels": species, "matrix": cm2} if cm2 is not None else None),
        "fold_details": fold_details,
        "notes": "Cross Validation results were precomputed and displayed in the Streamlit app.",
    }
    out_path = Path(args.out) if args.out else (Path(s.data_dir) / "derived" / "model_eval_cv_results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[CV] 저장 완료 → {out_path}")
    for r in all_results:
        print(f"  {r['model']:18} {r['validation_type']:22} "
              f"acc={r['accuracy_mean']}±{r['accuracy_std']} "
              f"top3={r['top3_accuracy_mean']}±{r['top3_accuracy_std']}")


if __name__ == "__main__":
    main()
