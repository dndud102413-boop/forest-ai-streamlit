"""
geo.py — 좌표계 안전 변환 · 래스터 셀 샘플링 · 경사/향 계산

────────────────────────────────────────────────────────────────────────
벡터(임상도) vs 래스터(DEM) — 사용자가 우려한 핵심 개념 정리
────────────────────────────────────────────────────────────────────────
사용자는 "shp 파일이 래스터(격자) 형태라, 사진 한 장의 점 좌표가 어느 격자
안에 들어가는지 계산하는 함수가 따로 필요한 것 아니냐"고 걱정했다.
실제 구조는 두 종류로 나뉜다.

1) 임상도(.shp)  =  **벡터 폴리곤** 데이터.
   - 격자가 아니라 임의 모양의 다각형(임분 경계)들의 집합이다.
   - 점이 어느 폴리곤에 속하는지는 *point-in-polygon* 연산으로 푼다.
     (geopandas: ``gdf.contains(point)`` / 공간조인 ``sjoin``)
   - 즉 "격자 안에 들어가는지" 계산이 아니라 "다각형 안에 들어가는지"이며,
     원본 노트북도 이미 ``forest.contains(point)``를 쓰고 있었다. → 별도
     격자 계산 함수는 임상도에는 필요 없다. (forest_map.py 참조)

2) DEM(.tif)  =  **래스터(격자)** 데이터.
   - 여기서는 사용자의 직관이 맞다. 점이 어느 픽셀(격자 셀)에 들어가는지
     찾아야 한다. 그것이 바로 ``dataset.index(x, y)`` → (row, col) 이고,
     ``array[row, col]`` 가 그 점이 떨어진 셀의 값이다.
   - 원본 노트북의 함정:
       (a) 위경도(EPSG:4326)를 좌표계 변환 없이 그대로 index()에 전달 →
           재투영된 DEM(EPSG:5179)에서는 엉뚱한 셀을 읽음.
       (b) 경계 밖 좌표가 음수 row/col을 만들면 numpy가 조용히 반대편
           픽셀을 읽어버림(silent wrap) → 잘못된 고도.
   - ``sample_raster()`` 가 (a) 좌표계 변환 (b) 경계검사 (c) nodata 처리
     (d) 선택적 bilinear 보간까지 모두 안전하게 처리한다.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Optional

import numpy as np

# pyproj / rasterio / shapely 는 무거우므로 함수 내부에서 지연 임포트할 수도
# 있으나, 본 모듈은 항상 사용되므로 상단에서 임포트한다.
from pyproj import Transformer


# ---------------------------------------------------------------------------
# 좌표계 변환 (단일 점) — Transformer 캐싱
# ---------------------------------------------------------------------------
@lru_cache(maxsize=64)
def _transformer(src_crs: str, dst_crs: str) -> Transformer:
    # always_xy=True → 입력/출력을 항상 (lon/x, lat/y) 순서로 다룬다.
    return Transformer.from_crs(src_crs, dst_crs, always_xy=True)


def transform_point(
    lon: float, lat: float, src_crs: str, dst_crs: str
) -> tuple[float, float]:
    """단일 점 (lon, lat) 을 src_crs → dst_crs 로 변환. 반환 (x, y)."""
    if str(src_crs) == str(dst_crs):
        return float(lon), float(lat)
    x, y = _transformer(str(src_crs), str(dst_crs)).transform(lon, lat)
    return float(x), float(y)


# ---------------------------------------------------------------------------
# 래스터 셀 샘플링 — 사용자가 요청한 "점이 어느 격자 셀에 들어가는지" 함수
# ---------------------------------------------------------------------------
class RasterSampleError(Exception):
    """좌표가 래스터 범위 밖이거나 nodata일 때."""


def sample_raster(
    dataset,
    lon: float,
    lat: float,
    point_crs: str = "EPSG:4326",
    band: int = 1,
    method: str = "nearest",
    array: Optional[np.ndarray] = None,
) -> float:
    """
    한 점이 떨어지는 래스터 셀의 값을 안전하게 반환한다.

    Parameters
    ----------
    dataset : rasterio.DatasetReader
        열린 래스터. (dataset.crs, dataset.bounds, dataset.index 사용)
    lon, lat : float
        질의 점 좌표 (point_crs 기준).
    point_crs : str
        질의 점의 좌표계. 기본 WGS84(GPS/EXIF).
    band : int
        1-base 밴드 번호.
    method : "nearest" | "bilinear"
        nearest = 점이 들어간 셀 값. bilinear = 주변 4셀 가중 보간.
    array : np.ndarray, optional
        이미 메모리에 올린 밴드 배열(있으면 재읽기 방지, slope/aspect 등).

    Returns
    -------
    float : 샘플 값.

    Raises
    ------
    RasterSampleError : 범위 밖 또는 nodata.
    """
    # (a) 좌표계 변환: 점을 래스터 좌표계로
    rcrs = str(dataset.crs) if dataset.crs else point_crs
    x, y = transform_point(lon, lat, point_crs, rcrs)

    # (b) 경계 검사 — 음수 인덱스 silent wrap 방지
    left, bottom, right, top = dataset.bounds
    if not (left <= x <= right and bottom <= y <= top):
        raise RasterSampleError(
            f"점({x:.1f},{y:.1f})이 래스터 범위 밖입니다 "
            f"bounds=({left:.1f},{bottom:.1f},{right:.1f},{top:.1f})"
        )

    nodata = dataset.nodata

    if method == "nearest":
        row, col = dataset.index(x, y)
        if not (0 <= row < dataset.height and 0 <= col < dataset.width):
            raise RasterSampleError(f"인덱스 범위 밖: row={row}, col={col}")
        if array is not None:
            val = float(array[row, col])
        else:
            val = float(dataset.read(band)[row, col])
        if nodata is not None and val == float(nodata):
            raise RasterSampleError("nodata 셀")
        if math.isnan(val):
            raise RasterSampleError("NaN 셀")
        return val

    elif method == "bilinear":
        return _bilinear(dataset, x, y, band, array, nodata)

    raise ValueError(f"알 수 없는 method: {method}")


def _bilinear(dataset, x, y, band, array, nodata) -> float:
    """4-이웃 bilinear 보간 (격자 경계 효과 완화)."""
    inv = ~dataset.transform  # 지도좌표 → 픽셀(부동소수) 좌표
    fcol, frow = inv * (x, y)
    # 픽셀 중심 기준으로 보간하기 위해 0.5 보정
    fcol -= 0.5
    frow -= 0.5
    c0, r0 = int(math.floor(fcol)), int(math.floor(frow))
    # 가장자리 반-픽셀 띠: bounds는 통과하지만 4-이웃 중 일부가 배열 밖일 수 있다.
    # 이웃 인덱스를 [0, width-2]/[0, height-2]로 클램프하고 가중치도 [0,1]로 클램프해
    # bounds 통과 점이 보간에서 예외로 탈락하지 않게 한다.
    c0 = min(max(c0, 0), dataset.width - 2)
    r0 = min(max(r0, 0), dataset.height - 2)
    dc = min(max(fcol - c0, 0.0), 1.0)
    dr = min(max(frow - r0, 0.0), 1.0)

    if array is None:
        array = dataset.read(band)

    def cell(r, c):
        if not (0 <= r < dataset.height and 0 <= c < dataset.width):
            raise RasterSampleError("보간 이웃이 범위 밖")
        v = float(array[r, c])
        if (nodata is not None and v == float(nodata)) or math.isnan(v):
            raise RasterSampleError("보간 이웃이 nodata")
        return v

    v00 = cell(r0, c0)
    v01 = cell(r0, c0 + 1)
    v10 = cell(r0 + 1, c0)
    v11 = cell(r0 + 1, c0 + 1)
    top = v00 * (1 - dc) + v01 * dc
    bot = v10 * (1 - dc) + v11 * dc
    return top * (1 - dr) + bot * dr


# ---------------------------------------------------------------------------
# 경사(slope) · 향(aspect) 계산
# ---------------------------------------------------------------------------
def compute_slope_aspect(
    dem_array: np.ndarray, xres: float, yres: float, nodata=None
) -> tuple[np.ndarray, np.ndarray]:
    """
    DEM 배열로부터 경사(도)와 향(도, 북=0, 시계방향) 배열을 계산.

    원본 노트북과 동일한 np.gradient 방식이되, nodata를 NaN으로 치환하고
    픽셀 해상도를 반영한다. *반드시 투영좌표계(미터 단위, 예: EPSG:5179)의*
    *DEM 배열에 적용해야 한다.* (지리좌표 4326의 도(degree) 해상도로 계산하면
    경사가 비현실적으로 나옴 — 노트북이 5179로 재투영한 이유)
    """
    arr = dem_array.astype("float64")
    if nodata is not None:
        arr = np.where(arr == nodata, np.nan, arr)

    # np.gradient: (d/dy, d/dx). yres는 보통 음수가 아닌 셀 크기로 전달.
    dy, dx = np.gradient(arr, yres, xres)
    slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
    slope_deg = np.degrees(slope_rad)

    aspect_rad = np.arctan2(-dx, dy)
    aspect_deg = np.degrees(aspect_rad)
    aspect_deg = np.where(aspect_deg < 0, 360 + aspect_deg, aspect_deg)
    # 평지(경사≈0)는 향이 정의되지 않는다. 마스킹하지 않으면 dx=dy=0 →
    # arctan2(-0,0)=0 → 항상 '북향'으로 잘못 인코딩된다(평평한 곳도 북향이 됨).
    flat = (np.abs(dx) < 1e-9) & (np.abs(dy) < 1e-9)
    aspect_deg = np.where(flat, np.nan, aspect_deg)
    return slope_deg, aspect_deg


# 8방위 (원본 노트북에서 호출되었으나 정의가 빠져 있어 크래시를 유발하던 함수)
_DIRS_8 = [
    "북향", "북동향", "동향", "남동향",
    "남향", "남서향", "서향", "북서향",
]


def aspect_to_direction(aspect_deg: float, n: int = 8) -> str:
    """
    향(0~360도, 북=0)을 한글 방위로 변환. 평지(NaN/음수)는 '평지'.

    원본 노트북의 make_growth_suitability / forest_ai_report 가
    ``aspect_to_direction`` 와 ``aspect_dir`` 컬럼을 사용했지만 정의가 없어
    NameError/KeyError 로 크래시했다. 이 함수가 그 결손을 메운다.
    """
    if aspect_deg is None or (isinstance(aspect_deg, float) and math.isnan(aspect_deg)):
        return "평지"
    if aspect_deg < 0:
        return "평지"
    a = float(aspect_deg) % 360
    if n == 8:
        idx = int((a + 22.5) // 45) % 8
        return _DIRS_8[idx]
    # 4방위
    idx = int((a + 45) // 90) % 4
    return ["북향", "동향", "남향", "서향"][idx]


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    """두 위경도 점 사이 대권거리(m). 경험적 인접 반경 계산용 보조."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
