"""
prepare_climate_data.py — stations.csv 정제/경량화 산출물 생성.

원본 data/stations.csv는 수정하지 않고 derived/ 아래에 분석용 정제본과 품질 리포트를 만든다.

사용:
    python scripts/prepare_climate_data.py
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

KEEP_COLUMNS = [
    "station", "sigungu", "mountain", "lat", "lon", "elev_m", "addr",
    "temp_c", "humidity_pct", "precip_mm", "wind_ms", "geocode_source", "confidence",
]
CONFIDENCE_WEIGHTS = {"high": 1.0, "med": 0.7, "low": 0.0}


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    repo = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default=str(repo / "data" / "stations.csv"))
    ap.add_argument("--out-dir", default=str(repo / "data" / "derived"))
    ap.add_argument("--keep-low", action="store_true", help="low confidence 관측소도 유지")
    args = ap.parse_args()

    src = Path(args.src)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    verified = out_dir / "stations_verified.csv"
    report_csv = out_dir / "climate_quality_report.csv"
    report_json = out_dir / "climate_quality_report.json"

    rows = []
    total = excluded_low = invalid_coord = cleaned_wind = missing_elev = 0
    confidence_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}

    with open(src, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            lat = _to_float(row.get("lat"))
            lon = _to_float(row.get("lon"))
            if lat is None or lon is None:
                invalid_coord += 1
                continue

            confidence = (row.get("confidence") or "med").strip().lower()
            if confidence == "low" and not args.keep_low:
                excluded_low += 1
                continue

            wind = _to_float(row.get("wind_ms"))
            if wind is not None and wind < 0:
                row["wind_ms"] = ""
                cleaned_wind += 1

            if _to_float(row.get("elev_m")) is None:
                missing_elev += 1

            clean_row = {c: row.get(c, "") for c in KEEP_COLUMNS}
            clean_row["confidence"] = confidence
            rows.append(clean_row)
            confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1
            gs = clean_row.get("geocode_source", "") or "unknown"
            source_counts[gs] = source_counts.get(gs, 0) + 1

    with open(verified, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=KEEP_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "source": str(src),
        "verified": str(verified),
        "source_bytes": src.stat().st_size,
        "verified_bytes": verified.stat().st_size,
        "source_rows": total,
        "verified_rows": len(rows),
        "excluded_low": excluded_low,
        "invalid_coord": invalid_coord,
        "cleaned_negative_wind": cleaned_wind,
        "missing_elev_m": missing_elev,
        "confidence_counts": confidence_counts,
        "geocode_source_counts": source_counts,
        "confidence_weights": CONFIDENCE_WEIGHTS,
    }

    with open(report_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(report_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        for key, value in summary.items():
            writer.writerow([key, json.dumps(value, ensure_ascii=False)
                             if isinstance(value, (dict, list)) else value])

    print(f"[climate] 원본 유지: {src} ({summary['source_bytes']} bytes)")
    print(f"[climate] 정제본 저장: {verified} ({summary['verified_bytes']} bytes)")
    print(f"[climate] 품질 리포트: {report_json}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
