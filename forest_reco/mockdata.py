"""
mockdata.py — 합성 임상도(벡터) + DEM(래스터) 생성기

실제 임상도/DEM(수 GB, 구글드라이브)이 없어도 전체 파이프라인을 end-to-end로
구동·테스트하기 위한 합성 데이터. 실제 데이터의 스키마(FRTP_NM, KOFTR_NM,
DMCLS_NM, AGCLS_NM, DNST_NM + 5179 폴리곤, 4326 DEM)를 동일하게 모사한다.

강원권 전체에 가까운 범위(경도 127.0~129.7, 위도 37.0~38.75)를 가정한
가상 지형을 만든다. 모바일 배포 데모에서 실제 GPS가 춘천 주변이 아니어도
기능 테스트가 가능하도록 넓은 범위를 사용한다.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .config import CRS_KOREA_TM, CRS_WGS84

# 합성 영역 (WGS84): 강원권 분석 안내 범위와 맞춘다.
BBOX = (127.00, 37.00, 129.70, 38.75)  # (lon_min, lat_min, lon_max, lat_max)


def _elevation_surface(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """위경도 격자에 대해 그럴듯한 고도(m) 표면 생성 (여러 가우시안 봉우리)."""
    peaks = [
        # (lon, lat, 높이, 폭)
        (127.65, 37.95, 1100, 0.10),
        (127.95, 37.75, 1400, 0.12),
        (128.10, 38.00, 800, 0.08),
        (127.58, 37.68, 500, 0.07),
    ]
    z = np.full(lon.shape, 80.0)  # 기저 고도(하천변)
    for plon, plat, h, w in peaks:
        z += h * np.exp(-(((lon - plon) ** 2 + (lat - plat) ** 2) / (2 * w ** 2)))
    # 능선/계곡 리플 — 현실적인 경사(slope)가 나오도록 가산
    z += 60 * np.sin(lon * 70) * np.cos(lat * 70)
    z += 25 * np.sin(lon * 180 + lat * 50)
    return np.maximum(z, 0.0)


def make_dem(path: str | Path, res_deg: float = 0.006) -> Path:
    """4326 DEM GeoTIFF 생성 (원본 gangwon_dem.tif와 동일 좌표계)."""
    import rasterio
    from rasterio.transform import from_origin

    lon0, lat0, lon1, lat1 = BBOX
    width = int(round((lon1 - lon0) / res_deg))
    height = int(round((lat1 - lat0) / res_deg))
    lons = lon0 + (np.arange(width) + 0.5) * res_deg
    lats = lat1 - (np.arange(height) + 0.5) * res_deg  # 위에서 아래로
    LON, LAT = np.meshgrid(lons, lats)
    elev = _elevation_surface(LON, LAT).astype("float32")

    transform = from_origin(lon0, lat1, res_deg, res_deg)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="float32", crs=CRS_WGS84, transform=transform, nodata=-9999.0,
    ) as dst:
        dst.write(elev, 1)
    return path


def _species_for(elev: float, rng) -> tuple[str, str]:
    """고도에 따라 (임종, 수종)을 그럴듯하게 배정."""
    if elev < 300:
        frtp, pool = "침엽수림", ["소나무", "리기다소나무", "곰솔"]
    elif elev < 700:
        frtp = rng.choice(["침엽수림", "활엽수림", "혼효림"], p=[0.4, 0.35, 0.25])
        if frtp == "침엽수림":
            pool = ["소나무", "일본잎갈나무"]
        elif frtp == "활엽수림":
            pool = ["굴참나무", "졸참나무", "상수리나무"]
        else:
            pool = ["소나무", "신갈나무"]
    elif elev < 1100:
        frtp = rng.choice(["활엽수림", "혼효림", "침엽수림"], p=[0.45, 0.3, 0.25])
        if frtp == "활엽수림":
            pool = ["신갈나무", "물푸레나무", "고로쇠나무"]
        elif frtp == "혼효림":
            pool = ["잣나무", "신갈나무"]
        else:
            pool = ["잣나무", "일본잎갈나무"]
    else:
        frtp = rng.choice(["침엽수림", "활엽수림"], p=[0.5, 0.5])
        pool = ["잣나무", "분비나무"] if frtp == "침엽수림" else ["신갈나무", "자작나무"]
    return frtp, str(rng.choice(pool))


def make_forest(path: str | Path, cell_m: float = 2000.0, seed: int = 42) -> Path:
    """5179 임상도 폴리곤 shapefile 생성 (격자형 임분 모사)."""
    import geopandas as gpd
    from shapely.geometry import box
    from pyproj import Transformer

    rng = np.random.default_rng(seed)
    lon0, lat0, lon1, lat1 = BBOX
    to5179 = Transformer.from_crs(CRS_WGS84, CRS_KOREA_TM, always_xy=True)
    to4326 = Transformer.from_crs(CRS_KOREA_TM, CRS_WGS84, always_xy=True)

    # 5179 영역 경계
    xs, ys = to5179.transform([lon0, lon1, lon0, lon1], [lat0, lat0, lat1, lat1])
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    geoms, recs = [], []
    age_classes = ["1영급", "2영급", "3영급", "4영급", "5영급", "6영급"]
    dm_classes = ["소경목", "중경목", "대경목"]
    dn_classes = ["소", "중", "밀"]

    y = ymin
    while y < ymax:
        x = xmin
        while x < xmax:
            cx, cy = x + cell_m / 2, y + cell_m / 2
            clon, clat = to4326.transform(cx, cy)
            # 합성 고도로 수종 배정
            elev = float(_elevation_surface(np.array([clon]), np.array([clat]))[0])
            frtp, koftr = _species_for(elev, rng)
            geoms.append(box(x, y, x + cell_m, y + cell_m))
            recs.append({
                "FRTP_NM": frtp,
                "KOFTR_NM": koftr,
                "DMCLS_NM": str(rng.choice(dm_classes, p=[0.4, 0.4, 0.2])),
                "AGCLS_NM": str(rng.choice(age_classes, p=[0.1, 0.2, 0.25, 0.2, 0.15, 0.1])),
                "DNST_NM": str(rng.choice(dn_classes, p=[0.3, 0.45, 0.25])),
            })
            x += cell_m
        y += cell_m

    gdf = gpd.GeoDataFrame(recs, geometry=geoms, crs=CRS_KOREA_TM)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, encoding="utf-8")
    return path


def ensure_mock_dataset(data_dir: str | Path) -> dict:
    """data_dir에 합성 DEM/임상도가 없으면 생성하고 경로 dict 반환."""
    data_dir = Path(data_dir)
    dem = data_dir / "gangwon_dem.tif"
    shp = data_dir / "51_1.shp"
    if not dem.exists():
        make_dem(dem)
    if not shp.exists():
        make_forest(shp)
    return {"dem": dem, "forest": [shp]}
