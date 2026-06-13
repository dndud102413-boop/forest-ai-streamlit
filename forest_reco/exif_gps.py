"""
exif_gps.py — 휴대폰 사진 EXIF에서 위경도(GPS) 추출

개발자 요구: "휴대폰에서 사진을 찍으면 그 사진의 위도·경도를 따온다."

실무 주의점(연구 반영):
- EXIF GPS 좌표는 항상 WGS84(EPSG:4326). 도/분/초(DMS)로 저장되며
  GPSLatitudeRef('N'/'S'), GPSLongitudeRef('E'/'W') 부호를 반드시 반영해야 한다.
  (남반구/서반구는 음수)
- 카카오톡/인스타 등을 거치거나 스크린샷이면 GPS가 제거(strip)되는 경우가 많다.
  → GPS가 없으면 None을 반환하고, 앱은 수동 좌표 입력/지도 선택으로 폴백한다.
- iPhone HEIC는 Pillow 단독으로 못 읽을 수 있어 pillow-heif가 있으면 사용한다.
- 일부 기기는 정확도(GPSHPositioningError), 고도(GPSAltitude)도 제공한다.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Union

from PIL import Image, ExifTags

# HEIC 지원(있으면 등록)
try:  # pragma: no cover - 환경 의존
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    _HEIF = True
except Exception:  # noqa: BLE001
    _HEIF = False

_GPSIFD = {v: k for k, v in ExifTags.GPSTAGS.items()}  # name -> id
ImageInput = Union[str, Path, bytes, io.BytesIO, Image.Image]


@dataclass
class GpsResult:
    lat: Optional[float]
    lon: Optional[float]
    altitude_m: Optional[float] = None
    accuracy_m: Optional[float] = None
    source: str = "exif"          # exif | none
    reason: str = ""              # 실패 사유(있을 때)

    @property
    def ok(self) -> bool:
        return self.lat is not None and self.lon is not None

    def as_dict(self) -> dict:
        return asdict(self)


def _to_float(x) -> float:
    """EXIF rational(IFDRational/tuple)을 float로."""
    try:
        return float(x)
    except (TypeError, ValueError):
        try:
            return float(x[0]) / float(x[1])
        except Exception:  # noqa: BLE001
            return float("nan")


def _dms_to_decimal(dms, ref) -> float:
    """(도, 분, 초) + 방위문자 → 십진 도."""
    d = _to_float(dms[0])
    m = _to_float(dms[1])
    s = _to_float(dms[2])
    dec = d + m / 60.0 + s / 3600.0
    if str(ref).upper() in ("S", "W"):
        dec = -dec
    return dec


def _open_image(image: ImageInput) -> Image.Image:
    if isinstance(image, Image.Image):
        return image
    if isinstance(image, (bytes, bytearray)):
        return Image.open(io.BytesIO(image))
    if isinstance(image, io.BytesIO):
        return Image.open(image)
    return Image.open(str(image))


def extract_gps(image: ImageInput) -> GpsResult:
    """
    사진에서 GPS를 추출한다. 경로/바이트/PIL.Image 모두 허용.
    GPS가 없으면 ok=False 인 GpsResult(reason 설명)를 돌려준다.
    """
    try:
        img = _open_image(image)
    except Exception as e:  # noqa: BLE001
        return GpsResult(None, None, source="none", reason=f"이미지 열기 실패: {e}")

    try:
        exif = img.getexif()
    except Exception as e:  # noqa: BLE001
        return GpsResult(None, None, source="none", reason=f"EXIF 읽기 실패: {e}")

    if not exif:
        return GpsResult(None, None, source="none", reason="EXIF 메타데이터 없음")

    # GPS IFD 추출 (Pillow 버전에 따라 두 경로 모두 시도)
    gps = {}
    try:
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo) or {}
    except Exception:  # noqa: BLE001
        gps = {}
    if not gps:
        raw = exif.get(_GPSIFD.get("GPSInfo", 34853))
        if isinstance(raw, dict):
            gps = raw

    if not gps:
        return GpsResult(None, None, source="none", reason="GPS 정보 없음(사진에 위치 미포함)")

    lat_dms = gps.get(_GPSIFD["GPSLatitude"])
    lat_ref = gps.get(_GPSIFD["GPSLatitudeRef"], "N")
    lon_dms = gps.get(_GPSIFD["GPSLongitude"])
    lon_ref = gps.get(_GPSIFD["GPSLongitudeRef"], "E")

    if not lat_dms or not lon_dms:
        return GpsResult(None, None, source="none", reason="위경도 태그 누락")

    try:
        lat = _dms_to_decimal(lat_dms, lat_ref)
        lon = _dms_to_decimal(lon_dms, lon_ref)
    except Exception as e:  # noqa: BLE001
        return GpsResult(None, None, source="none", reason=f"좌표 파싱 실패: {e}")

    # 유효 범위 검증
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return GpsResult(None, None, source="none", reason=f"좌표 범위 이상: {lat},{lon}")

    # 선택 정보
    alt = None
    if _GPSIFD.get("GPSAltitude") in gps:
        alt = _to_float(gps[_GPSIFD["GPSAltitude"]])
        if gps.get(_GPSIFD.get("GPSAltitudeRef")) in (1, b"\x01"):
            alt = -alt  # 해수면 아래
    acc = None
    if _GPSIFD.get("GPSHPositioningError") in gps:
        acc = _to_float(gps[_GPSIFD["GPSHPositioningError"]])

    return GpsResult(lat=round(lat, 7), lon=round(lon, 7),
                     altitude_m=alt, accuracy_m=acc, source="exif")


def write_gps_exif(src: ImageInput, lat: float, lon: float, dst_path: str) -> str:
    """
    테스트/데모용: 주어진 이미지에 GPS EXIF를 써서 저장한다.
    (실제 앱에는 불필요하지만, EXIF 파서를 검증하는 픽스처 생성에 쓴다.)
    """
    import piexif  # 지연 임포트(선택 의존성)

    def deg_to_dms_rational(deg_float):
        deg_float = abs(deg_float)
        d = int(deg_float)
        m = int((deg_float - d) * 60)
        s = round((deg_float - d - m / 60) * 3600 * 100)
        return ((d, 1), (m, 1), (s, 100))

    img = _open_image(src).convert("RGB")
    gps_ifd = {
        piexif.GPSIFD.GPSLatitudeRef: "N" if lat >= 0 else "S",
        piexif.GPSIFD.GPSLatitude: deg_to_dms_rational(lat),
        piexif.GPSIFD.GPSLongitudeRef: "E" if lon >= 0 else "W",
        piexif.GPSIFD.GPSLongitude: deg_to_dms_rational(lon),
    }
    exif_bytes = piexif.dump({"GPS": gps_ifd})
    img.save(dst_path, "jpeg", exif=exif_bytes)
    return dst_path
