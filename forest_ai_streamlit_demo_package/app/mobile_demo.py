"""Mobile-first Streamlit demo app for Forest AI."""
from __future__ import annotations

import os
import sys
from html import escape
from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forest_reco.demo_pipeline import (  # noqa: E402
    analyze_location,
    create_report,
    generate_explanation,
    is_gangwon,
    recommend_species,
)
from forest_reco.exif_gps import extract_gps  # noqa: E402


st.set_page_config(
    page_title="Forest AI",
    page_icon="🌲",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
.block-container { max-width: 680px; padding-top: 1rem; padding-bottom: 4rem; }
h1 { font-size: 2.15rem !important; letter-spacing: 0; margin-bottom: .15rem; }
h2, h3 { letter-spacing: 0; }
.hero { border: 1px solid #dce8dc; border-radius: 8px; padding: 16px 16px; background: #fbfdf9; margin: .25rem 0 1rem; }
.subtitle { font-size: 1.03rem; font-weight: 800; color: #1b5e20; margin-bottom: .45rem; }
.desc { color: #334238; font-size: .94rem; line-height: 1.58; }
.demo-badge { display: inline-block; padding: 4px 9px; border-radius: 8px; background: #e8f5e9; color: #1b5e20; font-size: .8rem; font-weight: 700; margin-bottom: .4rem; }
.input-card, .result-card { border: 1px solid #e1e5df; border-radius: 8px; padding: 13px 14px; background: #fff; margin: 10px 0; box-shadow: 0 1px 3px rgba(0,0,0,.04); }
.metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.metric { border: 1px solid #e6ebe4; border-radius: 8px; padding: 10px; background: #fbfdf9; }
.metric-label { font-size: .78rem; color: #5b6b5f; font-weight: 700; }
.metric-value { font-size: .98rem; color: #172017; margin-top: 2px; overflow-wrap: anywhere; }
.score-bar { height: 9px; border-radius: 8px; background: #edf0ec; overflow: hidden; margin: 7px 0 2px; }
.score-fill { height: 100%; background: linear-gradient(90deg, #66bb6a, #1b5e20); }
.stButton>button { width: 100%; min-height: 3rem; border-radius: 8px; font-weight: 800; }
.small-note { color: #617064; font-size: .86rem; line-height: 1.5; }
@media (max-width: 520px) {
  .block-container { padding-left: .8rem; padding-right: .8rem; }
  h1 { font-size: 1.85rem !important; }
  .metric-grid { grid-template-columns: 1fr; }
}
</style>
""",
    unsafe_allow_html=True,
)


def _init_state() -> None:
    ss = st.session_state
    ss.setdefault("lat", None)
    ss.setdefault("lon", None)
    ss.setdefault("source", None)
    ss.setdefault("gps_status", "waiting")
    ss.setdefault("gps_accuracy", None)
    ss.setdefault("result", None)


def _set_location(lat: float, lon: float, source: str) -> None:
    st.session_state.lat = float(lat)
    st.session_state.lon = float(lon)
    st.session_state.source = source


def _source_label(source: str | None) -> str:
    return {
        "gps": "현재 위치 GPS",
        "exif": "사진 EXIF GPS",
        "manual": "좌표 직접 입력",
    }.get(source or "", "위치 미선택")


def _try_browser_gps() -> bool:
    try:
        from streamlit_js_eval import get_geolocation

        loc = get_geolocation()
        coords = (loc or {}).get("coords") or {}
        if "latitude" in coords and "longitude" in coords:
            _set_location(float(coords["latitude"]), float(coords["longitude"]), "gps")
            acc = coords.get("accuracy")
            st.session_state.gps_accuracy = float(acc) if acc is not None else None
            st.session_state.gps_status = "ok"
            return True
        if st.session_state.gps_status != "ok":
            st.session_state.gps_status = "waiting"
    except Exception:
        if st.session_state.gps_status != "ok":
            st.session_state.gps_status = "error"
    return False


def _render_location_status() -> None:
    lat = st.session_state.lat
    lon = st.session_state.lon
    if lat is None or lon is None:
        st.info("아직 분석 위치가 선택되지 않았습니다. 아래 3가지 방식 중 하나를 선택해주세요.")
        return
    st.success(f"{_source_label(st.session_state.source)} 선택됨: 위도 {lat:.6f}, 경도 {lon:.6f}")
    if not is_gangwon(lat, lon):
        st.warning("현재 프로토타입은 강원도 지역 분석을 기준으로 합니다. 강원도 외 지역은 일부 데이터가 없을 수 있습니다.")


def _render_metrics(site_info: dict) -> None:
    terrain = site_info["terrain"]
    forest = site_info["forest_info"]
    diagnosis = site_info["diagnosis"]
    items = [
        ("고도", f"{terrain['elevation_m']} m"),
        ("경사", f"{terrain['slope_deg']} 도"),
        ("향", terrain["aspect_dir"]),
        ("기후대", site_info["climate_zone"]),
        ("임종", forest["임종"]),
        ("수종", forest["수종"]),
        ("영급", forest["영급"]),
        ("경급/밀도", f"{forest['경급']} / {forest['밀도']}"),
        ("생육 적합도", diagnosis["생육 적합도"]),
        ("병해충 취약도", diagnosis["병해충 취약도"]),
        ("관리 우선순위", diagnosis["관리 우선순위"]),
    ]
    st.markdown("<div class='metric-grid'>", unsafe_allow_html=True)
    for label, value in items:
        st.markdown(
            f"<div class='metric'><div class='metric-label'>{label}</div><div class='metric-value'>{value}</div></div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _run_analysis() -> None:
    lat = st.session_state.lat
    lon = st.session_state.lon
    if lat is None or lon is None:
        st.error("먼저 위치를 입력해주세요.")
        return
    try:
        site_info = analyze_location(float(lat), float(lon))
        recommendations = recommend_species(site_info)
        if not recommendations:
            st.warning("추천 가능한 수종 결과가 없습니다. 입력 위치를 확인하거나 다른 좌표로 다시 시도해주세요.")
            return
        explanation = generate_explanation(
            site_info,
            recommendations,
            gemini_api_key=st.session_state.get("gemini_key") or None,
        )
        report = create_report(site_info, recommendations, explanation)
        st.session_state.result = {
            "site_info": site_info,
            "recommendations": recommendations,
            "explanation": explanation,
            "report": report,
        }
    except Exception as exc:  # noqa: BLE001
        st.error("분석 중 문제가 발생했습니다. 좌표를 확인한 뒤 다시 시도해주세요.")
        with st.expander("오류 정보"):
            st.code(str(exc))


_init_state()

with st.sidebar:
    st.header("데모 설정")
    st.caption("무료 Streamlit Cloud 배포를 위해 대용량 GIS 파일 없이 동작하는 데모모드입니다.")
    st.session_state.gemini_key = st.text_input(
        "Gemini API Key (선택)",
        type="password",
        value=os.environ.get("GEMINI_API_KEY", ""),
    )
    st.info("Gemini 키가 없거나 실패하면 규칙 기반 보고서를 자동으로 제공합니다.")

st.markdown("<span class='demo-badge'>DEMO MODE</span>", unsafe_allow_html=True)
st.title("Forest AI")
st.markdown(
    """
<div class="hero">
  <div class="subtitle">산림 입지분석 기반 적지적수 의사결정 지원 서비스</div>
  <div class="desc">
    GPS 또는 숲 사진 위치정보를 기반으로 임상도, DEM, 입지환경 정보를 분석하여
    현재 숲의 상태를 진단하고 적합 수종과 관리 방향을 추천합니다.
  </div>
</div>
""",
    unsafe_allow_html=True,
)

st.subheader("1. 위치 입력")
tab_gps, tab_photo, tab_manual = st.tabs(["현재 위치", "숲 사진", "좌표 입력"])

with tab_gps:
    st.markdown("<div class='input-card'>스마트폰 브라우저의 위치 권한을 허용하면 현재 위치로 분석할 수 있습니다.</div>", unsafe_allow_html=True)
    gps_ok = _try_browser_gps()
    if gps_ok:
        acc = st.session_state.gps_accuracy
        suffix = f" / 정확도 약 {acc:.0f}m" if acc else ""
        st.success(f"현재 위치를 확인했습니다{suffix}.")
    elif st.session_state.gps_status == "error":
        st.warning("현재 위치 권한이 허용되지 않았습니다. 좌표를 직접 입력해주세요.")
    else:
        st.info("위치 권한 요청이 보이면 허용해주세요. 실패하면 좌표 입력 탭을 사용하면 됩니다.")

with tab_photo:
    st.markdown("<div class='input-card'>위치정보가 들어 있는 원본 숲 사진을 업로드하면 EXIF GPS를 읽습니다.</div>", unsafe_allow_html=True)
    uploaded = st.file_uploader("숲 사진 업로드", type=["jpg", "jpeg", "png", "heic"])
    if uploaded is not None:
        photo_bytes = uploaded.getvalue()
        st.image(photo_bytes, caption="업로드한 숲 사진", use_container_width=True)
        try:
            gps = extract_gps(photo_bytes)
            if gps.ok:
                _set_location(float(gps.lat), float(gps.lon), "exif")
                st.success(f"사진 위치정보를 찾았습니다: 위도 {gps.lat:.6f}, 경도 {gps.lon:.6f}")
            else:
                st.warning("사진에 위치정보가 없습니다. 좌표를 직접 입력해주세요.")
        except Exception:
            st.warning("사진의 위치정보를 읽지 못했습니다. 좌표를 직접 입력해주세요.")

with tab_manual:
    st.markdown("<div class='input-card'>강원도 예시 좌표가 기본값으로 들어 있습니다. 필요한 경우 직접 수정하세요.</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    default_lat = float(st.session_state.lat) if st.session_state.source == "manual" and st.session_state.lat is not None else 37.704054
    default_lon = float(st.session_state.lon) if st.session_state.source == "manual" and st.session_state.lon is not None else 128.330231
    lat_input = c1.number_input("위도 latitude", value=default_lat, format="%.6f")
    lon_input = c2.number_input("경도 longitude", value=default_lon, format="%.6f")
    if st.button("좌표를 분석 위치로 설정", use_container_width=True):
        if not (-90 <= lat_input <= 90 and -180 <= lon_input <= 180):
            st.error("위도와 경도를 올바른 숫자로 입력해주세요.")
        else:
            _set_location(float(lat_input), float(lon_input), "manual")
            st.success("좌표를 분석 위치로 저장했습니다.")

_render_location_status()

st.subheader("2. 숲 분석")
if st.button("숲 분석하기", type="primary", use_container_width=True):
    _run_analysis()

result = st.session_state.get("result")
if result:
    site_info = result["site_info"]
    recommendations = result["recommendations"]
    explanation = result["explanation"]
    report = result["report"]

    st.subheader("3. 산림 정보 및 입지 진단")
    _render_metrics(site_info)

    st.subheader("4. Top-3 적합 수종")
    for idx, rec in enumerate(recommendations, start=1):
        with st.expander(f"{idx}. 왜 {rec['species']}를 추천했나요? | 적합도 {rec['score']}점", expanded=(idx == 1)):
            st.markdown(f"**학명**: {rec['scientific_name']}")
            st.markdown(f"<div class='score-bar'><div class='score-fill' style='width:{rec['score']}%'></div></div>", unsafe_allow_html=True)
            st.markdown(f"**지형 적합성**  \n{rec['terrain_reason']}")
            st.markdown(f"**기후 적합성**  \n{rec['climate_reason']}")
            st.markdown(f"**현재 임상도와의 일치 여부**  \n{rec['forest_match_reason']}")
            st.markdown(f"**병해충 위험 감점 요인**  \n{rec['disease_risk_reason']}")
            st.markdown(f"**관리상 주의사항**  \n{rec['management_note']}")
            st.markdown(f"**최종 추천 이유**  \n{rec['final_reason']}")

    st.subheader("5. 자연어 진단 보고서")
    source_label = "Gemini" if explanation.get("source") == "gemini" else "규칙 기반 보고서"
    st.caption(source_label)
    safe_explanation = escape(explanation.get("text", "")).replace("\n", "<br>")
    st.markdown(f"<div class='result-card'>{safe_explanation}</div>", unsafe_allow_html=True)

    st.download_button(
        "HTML 보고서 다운로드",
        data=report.encode("utf-8"),
        file_name="forest_ai_demo_report.html",
        mime="text/html",
        use_container_width=True,
    )
