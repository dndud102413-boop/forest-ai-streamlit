"""Lightweight demo pipeline for the Forest AI mobile Streamlit prototype.

This module intentionally avoids heavy GIS dependencies and large data files.
It keeps the public demo flow stable on free Streamlit hosting:
location -> forest/site analysis -> Top-3 species recommendation -> report text.
"""
from __future__ import annotations

import math
import os
from datetime import datetime
from html import escape


GANGWON_BOUNDS = {
    "lat_min": 37.0,
    "lat_max": 38.75,
    "lon_min": 127.0,
    "lon_max": 129.7,
}


SPECIES_RULES = [
    {
        "name": "소나무",
        "scientific": "Pinus densiflora",
        "elev": (100, 900),
        "climate": {"온대중부", "온대북부"},
        "forest": {"침엽수림", "혼효림"},
        "caution": "건조한 남사면에서는 산불과 소나무재선충병 모니터링이 필요합니다.",
    },
    {
        "name": "잣나무",
        "scientific": "Pinus koraiensis",
        "elev": (400, 1200),
        "climate": {"온대북부", "냉온대"},
        "forest": {"침엽수림", "혼효림"},
        "caution": "초기 활착기에는 토양 수분과 한해 피해를 함께 확인하는 것이 좋습니다.",
    },
    {
        "name": "낙엽송",
        "scientific": "Larix kaempferi",
        "elev": (500, 1400),
        "climate": {"온대북부", "냉온대"},
        "forest": {"침엽수림", "혼효림"},
        "caution": "급경사지에서는 토양 유실과 초기 생장 관리가 중요합니다.",
    },
    {
        "name": "신갈나무",
        "scientific": "Quercus mongolica",
        "elev": (300, 1300),
        "climate": {"온대중부", "온대북부", "냉온대"},
        "forest": {"활엽수림", "혼효림"},
        "caution": "갱신 방식과 주변 경쟁 식생을 함께 고려해야 합니다.",
    },
    {
        "name": "자작나무",
        "scientific": "Betula platyphylla",
        "elev": (700, 1500),
        "climate": {"온대북부", "냉온대"},
        "forest": {"활엽수림", "혼효림"},
        "caution": "저지대나 고온 건조한 입지에서는 생육 안정성이 낮을 수 있습니다.",
    },
]


def is_gangwon(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    return (
        GANGWON_BOUNDS["lat_min"] <= lat <= GANGWON_BOUNDS["lat_max"]
        and GANGWON_BOUNDS["lon_min"] <= lon <= GANGWON_BOUNDS["lon_max"]
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _aspect_from_degrees(deg: float) -> str:
    dirs = ["북", "북동", "동", "남동", "남", "남서", "서", "북서"]
    return dirs[int((deg + 22.5) // 45) % 8]


def _demo_terrain(lat: float, lon: float) -> dict:
    peak_1 = math.exp(-(((lat - 37.75) ** 2 + (lon - 128.10) ** 2) / 0.055))
    peak_2 = math.exp(-(((lat - 38.05) ** 2 + (lon - 127.65) ** 2) / 0.075))
    wave = math.sin(lat * 16.0) * math.cos(lon * 13.0)
    elevation = _clamp(180 + 850 * peak_1 + 520 * peak_2 + 130 * wave, 80, 1450)
    slope = _clamp(7 + 24 * abs(math.sin(lat * 9.0 + lon * 4.0)), 3, 38)
    aspect_deg = (abs(math.sin(lat * 4.7) + math.cos(lon * 5.3)) * 180) % 360
    return {
        "elevation_m": round(elevation, 1),
        "slope_deg": round(slope, 1),
        "aspect_deg": round(aspect_deg, 1),
        "aspect_dir": _aspect_from_degrees(aspect_deg),
    }


def _climate_zone(lat: float, elevation_m: float) -> str:
    if elevation_m >= 900 or lat >= 38.1:
        return "냉온대"
    if elevation_m >= 450 or lat >= 37.6:
        return "온대북부"
    return "온대중부"


def analyze_location(lat: float, lon: float) -> dict:
    terrain = _demo_terrain(lat, lon)
    climate = _climate_zone(lat, terrain["elevation_m"])
    forest_type = "혼효림"
    if terrain["elevation_m"] < 420 and terrain["aspect_dir"] in {"남", "남서", "서"}:
        forest_type = "침엽수림"
        current_species = "소나무"
    elif terrain["elevation_m"] > 850:
        forest_type = "활엽수림"
        current_species = "신갈나무"
    else:
        current_species = "소나무-참나무류"

    density = "밀" if terrain["slope_deg"] < 18 else "중"
    disease_risk = "높음" if forest_type == "침엽수림" and terrain["aspect_dir"] in {"남", "남서"} else "보통"
    management = "우선 관리 필요" if disease_risk == "높음" or terrain["slope_deg"] >= 28 else "정기 관리 권장"

    return {
        "lat": lat,
        "lon": lon,
        "in_gangwon": is_gangwon(lat, lon),
        "terrain": terrain,
        "climate_zone": climate,
        "forest_info": {
            "임종": forest_type,
            "수종": current_species,
            "영급": "4영급" if terrain["elevation_m"] < 700 else "5영급",
            "경급": "중경목",
            "밀도": density,
        },
        "diagnosis": {
            "생육 적합도": "양호" if terrain["slope_deg"] < 25 else "보통",
            "병해충 취약도": disease_risk,
            "관리 우선순위": management,
        },
    }


def _range_score(value: float, low: float, high: float) -> tuple[float, str]:
    if low <= value <= high:
        return 1.0, f"고도 {value:.0f}m가 적정 범위({low:.0f}-{high:.0f}m)에 들어갑니다."
    distance = low - value if value < low else value - high
    score = _clamp(1.0 - distance / 500.0, 0.15, 0.82)
    return score, f"고도 {value:.0f}m가 적정 범위({low:.0f}-{high:.0f}m)와 일부 차이가 있습니다."


def recommend_species(site_info: dict) -> list[dict]:
    elevation = site_info["terrain"]["elevation_m"]
    slope = site_info["terrain"]["slope_deg"]
    aspect = site_info["terrain"]["aspect_dir"]
    climate = site_info["climate_zone"]
    forest_type = site_info["forest_info"]["임종"]
    disease_risk = site_info["diagnosis"]["병해충 취약도"]

    recs = []
    for sp in SPECIES_RULES:
        terrain_score, terrain_reason = _range_score(elevation, *sp["elev"])
        if slope >= 30:
            terrain_score *= 0.84
            terrain_reason += " 다만 경사가 커서 초기 활착 관리가 필요합니다."
        climate_score = 1.0 if climate in sp["climate"] else 0.62
        forest_score = 1.0 if forest_type in sp["forest"] else 0.72
        disease_penalty = 8 if disease_risk == "높음" and sp["name"] == "소나무" else 3 if disease_risk == "높음" else 0
        aspect_bonus = 3 if sp["name"] == "소나무" and aspect in {"남", "남서", "서"} else 0
        score = (terrain_score * 42) + (climate_score * 26) + (forest_score * 20) + 9 + aspect_bonus - disease_penalty
        score = round(_clamp(score, 0, 98), 1)
        recs.append(
            {
                "species": sp["name"],
                "scientific_name": sp["scientific"],
                "score": score,
                "terrain_reason": terrain_reason,
                "climate_reason": (
                    f"{climate} 기후대와 생육 특성이 잘 맞습니다."
                    if climate_score == 1.0
                    else f"{climate} 기후대에서도 가능하지만 최적 조건은 아니므로 현장 확인이 필요합니다."
                ),
                "forest_match_reason": (
                    f"현재 임상도상 {forest_type}과 수종 특성이 잘 맞습니다."
                    if forest_score == 1.0
                    else f"현재 임상도상 {forest_type}과 완전히 일치하지 않아 보조 후보로 판단했습니다."
                ),
                "disease_risk_reason": (
                    f"병해충 취약도가 {disease_risk}으로 평가되어 {disease_penalty}점 감점했습니다."
                    if disease_penalty
                    else "현재 데모 진단에서는 큰 병해충 감점 요인이 확인되지 않았습니다."
                ),
                "management_note": sp["caution"],
                "final_reason": f"{sp['name']}는 지형, 기후, 현재 임상 정보를 종합했을 때 데모 분석 기준 적합도가 높습니다.",
            }
        )
    return sorted(recs, key=lambda item: item["score"], reverse=True)[:3]


def generate_explanation(site_info: dict, recommendations: list[dict], gemini_api_key: str | None = None) -> dict:
    if gemini_api_key:
        try:
            from google import genai

            client = genai.Client(api_key=gemini_api_key)
            top = ", ".join(f"{r['species']}({r['score']}점)" for r in recommendations)
            prompt = (
                "비전문가가 이해하기 쉬운 한국어로 산림 입지 분석 보고서 요약을 5문장 이내로 작성하세요.\n"
                f"위치: 위도 {site_info['lat']:.5f}, 경도 {site_info['lon']:.5f}\n"
                f"지형: 고도 {site_info['terrain']['elevation_m']}m, 경사 {site_info['terrain']['slope_deg']}도, "
                f"향 {site_info['terrain']['aspect_dir']}\n"
                f"임상: {site_info['forest_info']}\n"
                f"추천 수종: {top}\n"
            )
            response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            text = (response.text or "").strip()
            if text:
                return {"source": "gemini", "text": text}
        except Exception as exc:  # noqa: BLE001
            fallback = _fallback_explanation(site_info, recommendations)
            return {
                "source": "fallback",
                "text": "AI 요약 생성에 실패하여 기본 규칙 기반 보고서를 제공합니다.\n\n" + fallback,
                "error": str(exc),
            }
    return {"source": "fallback", "text": _fallback_explanation(site_info, recommendations)}


def _fallback_explanation(site_info: dict, recommendations: list[dict]) -> str:
    terrain = site_info["terrain"]
    forest = site_info["forest_info"]
    diag = site_info["diagnosis"]
    top_names = ", ".join(r["species"] for r in recommendations[:3]) or "추천 수종 없음"
    return (
        f"해당 위치는 고도 {terrain['elevation_m']}m, 경사 {terrain['slope_deg']}도, "
        f"{terrain['aspect_dir']}향의 입지로 분석되었습니다. "
        f"현재 임상도 기준으로는 {forest['임종']}이며 주요 수종은 {forest['수종']}으로 추정됩니다. "
        f"생육 적합도는 {diag['생육 적합도']}, 병해충 취약도는 {diag['병해충 취약도']}으로 진단했습니다. "
        f"종합 추천 수종은 {top_names}이며, 지형 조건과 기후 조건, 현재 임상과의 일치도를 함께 고려했습니다. "
        "본 결과는 데모모드 분석이므로 실제 조림 전에는 현장 토양, 배수, 병해충 이력 확인이 필요합니다."
    )


def create_report(site_info: dict, recommendations: list[dict], explanation: dict) -> str:
    rows = []
    for label, value in [
        ("위도", f"{site_info['lat']:.6f}"),
        ("경도", f"{site_info['lon']:.6f}"),
        ("고도", f"{site_info['terrain']['elevation_m']}m"),
        ("경사", f"{site_info['terrain']['slope_deg']}도"),
        ("향", site_info["terrain"]["aspect_dir"]),
        ("기후대", site_info["climate_zone"]),
        ("임종", site_info["forest_info"]["임종"]),
        ("수종", site_info["forest_info"]["수종"]),
        ("영급", site_info["forest_info"]["영급"]),
        ("경급", site_info["forest_info"]["경급"]),
        ("밀도", site_info["forest_info"]["밀도"]),
        ("생육 적합도", site_info["diagnosis"]["생육 적합도"]),
        ("병해충 취약도", site_info["diagnosis"]["병해충 취약도"]),
        ("관리 우선순위", site_info["diagnosis"]["관리 우선순위"]),
    ]:
        rows.append(f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>")

    rec_html = []
    for i, rec in enumerate(recommendations, 1):
        rec_html.append(
            f"<section class='card'><h3>{i}. {escape(rec['species'])} "
            f"<small>{escape(rec['scientific_name'])}</small></h3>"
            f"<p><b>적합도:</b> {rec['score']}점</p>"
            f"<ul><li>{escape(rec['terrain_reason'])}</li>"
            f"<li>{escape(rec['climate_reason'])}</li>"
            f"<li>{escape(rec['forest_match_reason'])}</li>"
            f"<li>{escape(rec['disease_risk_reason'])}</li>"
            f"<li>{escape(rec['management_note'])}</li></ul></section>"
        )

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>Forest AI 데모 보고서</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 28px; line-height: 1.6; color: #172017; }}
    h1 {{ color: #1b5e20; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d9e2d9; padding: 8px 10px; text-align: left; }}
    th {{ width: 34%; background: #f1f8e9; }}
    .card {{ border: 1px solid #d9e2d9; border-radius: 8px; padding: 12px 14px; margin: 12px 0; }}
    .note {{ background: #f7faf7; border-left: 4px solid #2e7d32; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Forest AI 데모 분석 보고서</h1>
  <p class="note">생성일시: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 본 보고서는 Streamlit Cloud 배포용 데모모드 결과입니다.</p>
  <h2>1. 위치 및 산림 정보</h2>
  <table>{''.join(rows)}</table>
  <h2>2. Top-3 추천 수종</h2>
  {''.join(rec_html)}
  <h2>3. 자연어 설명</h2>
  <p>{escape(explanation.get('text', ''))}</p>
</body>
</html>"""

