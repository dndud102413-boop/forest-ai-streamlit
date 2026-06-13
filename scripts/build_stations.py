"""
build_stations.py — 산악기상관측소(AI data.xlsx)의 좌표를 채워 stations.csv 생성.

AI data.xlsx는 강원권 149개 산악기상관측소의 기온/습도/강수량/풍속을 담고 있으나 위·경도가
비어 있다. 이 스크립트는 좌표를 다음 우선순위로 채운다:

  1) 국립산림과학원 산악기상관측시스템(mw.nifos.go.kr)의 공식 '전 지점 현황'에서
     각 관측소의 **읍면/리 단위 주소 + 고도**를 가져와(권위 있는 위치), 그 주소를
     지오코딩(리→면→시군 캐스케이드). 고도(elev_m)도 함께 채운다.
  2) NIFOS 매칭/지오코딩 실패 시: 산이름 OSM 지오코딩.
  3) 그래도 실패 시: 시군 중심좌표.

좌표는 리(里) 단위라 시군 중심보다 훨씬 정밀하나 여전히 근사다(관측소는 그 리의 산봉우리).
정밀 위경도가 필요하면 data.go.kr '산악기상관측 OpenAPI'(serviceKey 필요)를 쓰면 된다.

사용:
    python scripts/build_stations.py
    python scripts/build_stations.py --no-nifos   # NIFOS 미사용(산이름+시군만)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

# 강원(+경기 일부) bbox(WGS84) — 지오코딩 결과 검증.
BBOX = (126.8, 36.5, 129.7, 38.8)  # lon_min, lat_min, lon_max, lat_max

SIGUNGU_CENTROID = {
    "가평": (37.831, 127.510), "강릉": (37.752, 128.876), "고성": (38.381, 128.468),
    "동해": (37.525, 129.114), "삼척": (37.450, 129.165), "양구": (38.110, 127.990),
    "양양": (38.075, 128.619), "영월": (37.184, 128.462), "원주": (37.342, 127.920),
    "인제": (38.070, 128.170), "정선": (37.380, 128.661), "철원": (38.147, 127.313),
    "춘천": (37.881, 127.730), "태백": (37.164, 128.986), "평창": (37.370, 128.390),
    "홍천": (37.697, 127.889), "화천": (38.106, 127.708), "횡성": (37.491, 127.985),
}
SPECIAL_SIGUNGU = {"국립춘천숲체원": "춘천", "철원남북산림협력센터": "철원"}
NIFOS_URL = "http://mw.nifos.go.kr/kfs/SiteState/AllSiteStateList.do"


def _in_bbox(lat, lon):
    return BBOX[1] <= lat <= BBOX[3] and BBOX[0] <= lon <= BBOX[2]


def fetch_nifos() -> dict:
    """NIFOS 전 지점 현황 → {지점명: {addr, alt}}."""
    req = urllib.request.Request(
        NIFOS_URL, headers={"User-Agent": "Mozilla/5.0",
                            "Referer": "http://mw.nifos.go.kr/kfs/SiteState/SiteState.do?StateType=List"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    rows = re.findall(
        r"fnThisSiteInfoDisplay\(this,\s*'([^']*)',\s*'([^']*)',\s*'([^']*)'\)[^>]*>\s*[\d]+\.([^<]+)</td>",
        html)
    out = {}
    for addr, _jibun, alt, name in rows:
        try:
            altf = float(alt)
        except ValueError:
            altf = None
        out[name.strip()] = {"addr": addr.strip(), "alt": altf}
    return out


def geocode(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "json", "limit": 1, "countrycodes": "kr"})
    req = urllib.request.Request(url, headers={"User-Agent": "forest-ai-stations/1.0"})
    d = json.load(urllib.request.urlopen(req, timeout=15))
    if d:
        return float(d[0]["lat"]), float(d[0]["lon"])
    return None


def geocode_address(addr: str, delay: float):
    """리→면→시군 캐스케이드(+ '강원도' 대체). (lat, lon, level) 또는 None."""
    toks = addr.split()
    cands = []
    if len(toks) >= 4:
        cands.append((" ".join(toks), "ri"))
    if len(toks) >= 3:
        cands.append((" ".join(toks[:3]), "myeon"))
    if len(toks) >= 2:
        cands.append((" ".join(toks[:2]), "sigungu"))
    seen = set()
    for q, level in cands:
        for qq in (q, q.replace("강원특별자치도", "강원도")):
            if qq in seen:
                continue
            seen.add(qq)
            try:
                r = geocode(qq)
            except Exception:
                r = None
            time.sleep(delay)
            if r and _in_bbox(*r):
                return r[0], r[1], level
    return None


def main() -> None:
    repo = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default=str(repo.parent / "AI  data.xlsx"))
    ap.add_argument("--out", default=str(repo / "data" / "stations.csv"))
    ap.add_argument("--delay", type=float, default=1.1)
    ap.add_argument("--no-nifos", action="store_true")
    a = ap.parse_args()

    nifos = {}
    if not a.no_nifos:
        try:
            nifos = fetch_nifos()
            print(f"[nifos] 전 지점 현황 {len(nifos)}개 로드(주소+고도)")
        except Exception as e:
            print(f"[nifos] 로드 실패({e}) → 산이름+시군 폴백 사용")

    df = pd.read_excel(a.xlsx, header=2).dropna(how="all")
    stations = df["지점"].dropna().astype(str).tolist()
    rows = []
    cnt = {"nifos_ri": 0, "nifos_myeon": 0, "nifos_sigungu": 0, "osm_mountain": 0,
           "sigungu_centroid": 0, "none": 0}
    print(f"[stations] {len(stations)}개 지오코딩 시작(간격 {a.delay}s)…")

    for i, st in enumerate(stations, 1):
        rec = df[df["지점"] == st].iloc[0]
        sgg = SPECIAL_SIGUNGU.get(st, st.split()[0])
        info = nifos.get(st, {})
        addr, alt = info.get("addr"), info.get("alt")

        lat = lon = src = conf = None
        # 1) NIFOS 주소 지오코딩(리→면→시군)
        if addr:
            g = geocode_address(addr, a.delay)
            if g:
                lat, lon = g[0], g[1]
                src = {"ri": "nifos_ri", "myeon": "nifos_myeon",
                       "sigungu": "nifos_sigungu"}[g[2]]
                conf = {"ri": "high", "myeon": "med", "sigungu": "low"}[g[2]]
        # 2) 산이름 OSM
        if lat is None:
            try:
                mtn = re.sub(r"\([^)]*\)", "", st.split(maxsplit=1)[-1]).strip()
                r = geocode(f"{mtn} {sgg} 강원")
            except Exception:
                r = None
            time.sleep(a.delay)
            if r and _in_bbox(*r):
                lat, lon, src, conf = r[0], r[1], "osm_mountain", "med"
        # 3) 시군 중심
        if lat is None:
            c = SIGUNGU_CENTROID.get(sgg)
            if c:
                lat, lon, src, conf = c[0], c[1], "sigungu_centroid", "low"
            else:
                src, conf = "none", "none"
        cnt[src] = cnt.get(src, 0) + 1

        rows.append({
            "station": st, "sigungu": sgg,
            "mountain": st.split(maxsplit=1)[1] if " " in st else st,
            "lat": round(lat, 6) if lat is not None else "",
            "lon": round(lon, 6) if lon is not None else "",
            "elev_m": alt if alt is not None else "",
            "addr": addr or "",
            "temp_c": rec.get("기온 (℃)"), "humidity_pct": rec.get("습도 (%)"),
            "precip_mm": rec.get("강수량"), "wind_ms": rec.get("풍속 (m/s)"),
            "geocode_source": src, "confidence": conf,
        })
        if i % 15 == 0 or i == len(stations):
            print(f"  {i:3d}/{len(stations)}  {dict((k, v) for k, v in cnt.items() if v)}")

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["station", "sigungu", "mountain", "lat", "lon", "elev_m", "addr",
              "temp_c", "humidity_pct", "precip_mm", "wind_ms",
              "geocode_source", "confidence"]
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    hi = cnt["nifos_ri"]
    print(f"\n[stations] 저장: {out} ({len(rows)}행)")
    print(f"  출처: {dict((k, v) for k, v in cnt.items() if v)}")
    print(f"  고정밀(리 단위) {hi}개 · 고도 채움 {sum(1 for r in rows if r['elev_m'] != '')}개")


if __name__ == "__main__":
    main()
