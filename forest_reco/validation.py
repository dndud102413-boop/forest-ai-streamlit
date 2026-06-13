"""Optional validation metrics for external validation_data.csv."""
from __future__ import annotations

from pathlib import Path


def validation_path(data_dir: Path) -> Path:
    return Path(data_dir) / "validation_data.csv"


def evaluate_validation(data_dir: Path, analyze_fn, sources) -> dict:
    """Evaluate Top-1, macro F1, and Top-3 only when validation_data.csv exists.

    Expected columns: lat, lon, true_species
    """
    import pandas as pd
    from sklearn.metrics import f1_score

    path = validation_path(data_dir)
    if not path.exists():
        return {
            "available": False,
            "message": "현 프로토타입에는 별도 검증 데이터셋이 연결되어 있지 않아 정량 검증지표는 계산하지 않습니다.",
            "expected_file": str(path),
            "expected_columns": ["lat", "lon", "true_species"],
        }

    df = pd.read_csv(path)
    required = {"lat", "lon", "true_species"}
    missing = sorted(required - set(df.columns))
    if missing:
        return {
            "available": False,
            "message": f"validation_data.csv에 필요한 컬럼이 없습니다: {', '.join(missing)}",
            "expected_file": str(path),
            "expected_columns": ["lat", "lon", "true_species"],
        }

    y_true, y_pred = [], []
    top1_hits = 0
    top3_hits = 0
    total = 0
    for _, row in df.iterrows():
        try:
            res = analyze_fn(
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                sources=sources,
                explain=False,
                use_sdm=True,
                top_k=3,
            )
            recs = res.get("recommendations") or []
            names = [r.get("수종") for r in recs if r.get("수종")]
            if not names:
                continue
            true = str(row["true_species"]).strip()
            pred = names[0]
            y_true.append(true)
            y_pred.append(pred)
            total += 1
            if pred == true:
                top1_hits += 1
            if true in names[:3]:
                top3_hits += 1
        except Exception:
            continue

    if total == 0:
        return {
            "available": False,
            "message": "검증 데이터는 있으나 계산 가능한 행이 없습니다.",
            "expected_file": str(path),
        }

    return {
        "available": True,
        "n": total,
        "top1_accuracy": round(top1_hits / total, 3),
        "top3_accuracy": round(top3_hits / total, 3),
        "macro_f1": round(float(f1_score(y_true, y_pred, average="macro")), 3),
        "file": str(path),
    }
