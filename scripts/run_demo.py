"""
run_demo.py — 콘솔에서 파이프라인을 빠르게 확인하는 데모

    python scripts/run_demo.py --lat 37.95 --lon 127.66 --goal 탄소흡수 --mock
    python scripts/run_demo.py --photo my_photo.jpg --mock
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forest_reco.pipeline import analyze, DataSources  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--photo")
    ap.add_argument("--goal", default=None)
    ap.add_argument("--audience", default="시민")
    ap.add_argument("--mock", action="store_true", help="합성 데이터 사용")
    ap.add_argument("--topk", type=int, default=6)
    a = ap.parse_args()

    src = DataSources(use_mock=a.mock)
    res = analyze(photo=a.photo, lat=a.lat, lon=a.lon, goal=a.goal,
                  audience=a.audience, sources=src, top_k=a.topk)

    if not res["ok"]:
        print("[실패]", res["message"])
        return
    s = res["site"]
    print("=" * 64)
    print(f"위치: {s['lat']}, {s['lon']}  (출처 {res['location'].get('source')})")
    print(f"입지: {s['climate_zone']} / 고도 {s['elevation_m']}m / 경사 {s['slope_deg']}° / {s['aspect_dir']}")
    fi = res.get("forest_info")
    if fi:
        print(f"현장임상: {fi.get('임종')} · {fi.get('수종')} · {fi.get('경급')} · {fi.get('영급')}")
    print("-" * 64)
    print(f"{'순위':<4}{'수종':<12}{'점수':>6}  근거")
    for i, r in enumerate(res["recommendations"], 1):
        print(f"{i:<4}{r['수종']:<12}{r['적합점수']:>6.1f}  {', '.join(r['주요근거'][:2])}")
    print("-" * 64)
    print("[AI 설명 / 출처:", res["explanation"]["source"], "]")
    print(res["explanation"]["text"])


if __name__ == "__main__":
    main()
