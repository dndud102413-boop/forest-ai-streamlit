"""
climate_map.py — 149개 산악기상관측소 값을 IDW로 보간해 강원 전역 기온 분포도(PNG) 생성.

사용자 요청: "153개 관측점/값으로 강원도 전체 래스터 픽셀에 값을 부여" → IDW 보간.
DEM(gangwon_dem.tif) 유효 픽셀에만 색을 칠해 실제 강원 형상으로 렌더한다(나머지 투명).
matplotlib 없이 Pillow(numpy)만으로 컬러맵·관측소 점을 그린다.

산출물: data/climate_map_temp.png (앱의 '강원 기온 분포' 지도에 표시)

사용:
    python scripts/climate_map.py
    python scripts/climate_map.py --var precip_mm --width 360
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _colormap(t):
    """0~1 정규화값 → RGB. 파랑(저온)→청록→초록→노랑→빨강(고온)."""
    stops = [(0.0, (33, 102, 172)), (0.25, (67, 162, 202)), (0.5, (120, 198, 121)),
             (0.75, (254, 204, 92)), (1.0, (215, 48, 39))]
    t = float(np.clip(t, 0, 1))
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if t <= b:
            f = (t - a) / (b - a) if b > a else 0.0
            return tuple(int(ca[i] + (cb[i] - ca[i]) * f) for i in range(3))
    return stops[-1][1]


def main() -> None:
    repo = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", default=str(repo / "data" / "stations.csv"))
    ap.add_argument("--dem", default=str(repo / "data" / "gangwon_dem.tif"))
    ap.add_argument("--var", default="temp_c", choices=["temp_c", "precip_mm"])
    ap.add_argument("--width", type=int, default=320, help="출력 가로 픽셀(다운샘플)")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--power", type=float, default=1.2)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    import rasterio
    from rasterio.enums import Resampling
    from PIL import Image, ImageDraw
    from forest_reco.observed_climate import ObservedClimate

    obs = ObservedClimate.from_csv(a.stations)
    if obs is None:
        raise SystemExit("stations.csv 없음/유효좌표 없음")
    s_lat = np.array([s.lat for s in obs.stations])
    s_lon = np.array([s.lon for s in obs.stations])
    s_val = np.array([getattr(s, a.var) if getattr(s, a.var) is not None else np.nan
                      for s in obs.stations])
    ok = ~np.isnan(s_val)
    s_lat, s_lon, s_val = s_lat[ok], s_lon[ok], s_val[ok]

    # 동일/근접 좌표(시군 중심 폴백 다수)에서 값이 충돌해 IDW '과녁' 잡음이 생기므로,
    # 같은 좌표(소수 5자리)로 묶어 값을 평균해 대표점화한다(정확 좌표 확보 시 불필요).
    agg = {}
    for la, lo, v in zip(s_lat, s_lon, s_val):
        key = (round(la, 4), round(lo, 4))
        agg.setdefault(key, []).append(v)
    s_lat = np.array([k[0] for k in agg])
    s_lon = np.array([k[1] for k in agg])
    s_val = np.array([float(np.mean(vs)) for vs in agg.values()])
    print(f"  관측소 {int(ok.sum())}개 → 대표점 {len(s_val)}개(동일좌표 평균)")

    # DEM을 가로 width로 다운샘플 → 픽셀별 lon/lat + 유효(육지/강원) 마스크
    with rasterio.open(a.dem) as ds:
        scale = a.width / ds.width
        h = max(1, int(ds.height * scale))
        dem = ds.read(1, out_shape=(h, a.width), resampling=Resampling.average)
        tr = ds.transform * ds.transform.scale(ds.width / a.width, ds.height / h)
        nodata = ds.nodata
    H, W = dem.shape
    cols, rows = np.meshgrid(np.arange(W), np.arange(H))
    xs = tr.c + tr.a * (cols + 0.5)   # lon
    ys = tr.f + tr.e * (rows + 0.5)   # lat
    valid = np.isfinite(dem)
    if nodata is not None:
        valid &= (dem != nodata)
    valid &= (dem > 0)      # 병합 DEM의 빈칸(0 채움)·해수 제거 → 강원 형상으로 마스킹

    # IDW 보간(벡터화: 관측소별 누적)
    num = np.zeros((H, W)); den = np.zeros((H, W))
    coslat = math.cos(math.radians(float(np.nanmean(ys))))
    for la, lo, v in zip(s_lat, s_lon, s_val):
        d2 = ((ys - la)) ** 2 + ((xs - lo) * coslat) ** 2
        d2 = np.maximum(d2, 1e-9)
        w = 1.0 / (d2 ** (a.power / 2.0))
        num += w * v; den += w
    grid = np.where(den > 0, num / den, np.nan)

    # 가우시안 평활 — IDW '과녁'(정확보간 + 거친 좌표) 잡음을 지역 분포로 부드럽게.
    try:
        from scipy.ndimage import gaussian_filter
        fill = float(np.nanmean(grid[valid]))
        gfilled = np.where(np.isfinite(grid), grid, fill)
        grid = gaussian_filter(gfilled, sigma=max(4.0, W / 40.0))
    except Exception:  # noqa: BLE001
        pass

    vmin, vmax = np.nanpercentile(grid[valid], [2, 98])
    rgba = np.zeros((H, W, 4), dtype="uint8")
    for r in range(H):
        for c in range(W):
            if valid[r, c] and np.isfinite(grid[r, c]):
                t = (grid[r, c] - vmin) / (vmax - vmin + 1e-9)
                rgba[r, c, :3] = _colormap(t)
                rgba[r, c, 3] = 235
    img = Image.fromarray(rgba, "RGBA")

    # 관측소 점 오버레이
    draw = ImageDraw.Draw(img)

    def to_px(la, lo):
        c = (lo - tr.c) / tr.a; r = (la - tr.f) / tr.e
        return c, r
    for la, lo in zip(s_lat, s_lon):
        c, r = to_px(la, lo)
        draw.ellipse([c - 1.6, r - 1.6, c + 1.6, r + 1.6],
                     fill=(20, 20, 20, 255), outline=(255, 255, 255, 255))

    out = Path(a.out) if a.out else repo / "data" / f"climate_map_{a.var}.png"
    img.save(out)
    label = "기온(℃)" if a.var == "temp_c" else "강수(mm)"
    print(f"[climate_map] 저장: {out}  ({W}x{H}px, {label} {vmin:.1f}~{vmax:.1f}, "
          f"관측소 {len(s_val)}개, IDW k={a.k} power={a.power})")


if __name__ == "__main__":
    main()
