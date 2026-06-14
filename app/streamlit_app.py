"""
streamlit_app.py — 모바일 산림 수종 추천 AI (모바일 반응형 프로토타입)

실행:
    streamlit run app/streamlit_app.py

원본 노트북의 Streamlit 데모를 다음과 같이 확장/정비했다.
- 위치 입력 3경로: ① 사진(EXIF GPS) ② 현재 위치(GPS) ③ 지도/좌표 직접입력
- 식재 "추천 수종" 카드 + 적합 근거 + 유의사항 (원본엔 없던 핵심 기능)
- Gemini 설명(키 입력 시) / 키 없으면 오프라인 폴백 설명
- 식재 목적·독자(타겟층) 선택으로 다양한 사용자 대응
- 실데이터 없으면 합성데이터로 자동 구동(데모 모드)
"""
from __future__ import annotations

import os
import sys
import json
from html import escape as html_escape
from pathlib import Path

import streamlit as st

# 패키지 import 경로 보장
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forest_reco.pipeline import analyze, DataSources  # noqa: E402
from forest_reco.recommender import GOALS  # noqa: E402
from forest_reco.llm import AUDIENCES  # noqa: E402
from forest_reco.config import Settings  # noqa: E402
from forest_reco.report import create_report, create_pdf_report, report_filename  # noqa: E402
from forest_reco.validation import evaluate_validation  # noqa: E402

st.set_page_config(page_title="산림 수종 추천 AI", page_icon="🌲",
                   layout="centered", initial_sidebar_state="collapsed")

# 브라우저 자동번역(크롬/엣지/웨일/파파고)이 React 텍스트 노드를 바꿔치기하면
# "Failed to execute 'removeChild' on 'Node'" 프론트 오류로 앱 전체가 죽는다.
# 부모 문서에 notranslate를 지정해 자동번역 자체를 막는다(srcdoc → same-origin).
import streamlit.components.v1 as _components  # noqa: E402
_components.html(
    """
    <script>
    try {
      var d = window.parent.document;
      d.documentElement.setAttribute('translate', 'no');
      d.documentElement.classList.add('notranslate');
      d.documentElement.lang = 'ko';
      if (!d.querySelector('meta[name="google"]')) {
        var m = d.createElement('meta');
        m.name = 'google'; m.content = 'notranslate';
        (d.head || d.documentElement).appendChild(m);
      }
    } catch (e) {}
    </script>
    """,
    height=0,
)

for _secret_key in ("GEMINI_API_KEY", "FOREST_RECO_DATA_BUNDLE_URL", "FOREST_RECO_DEMO"):
    try:
        if _secret_key in st.secrets and not os.environ.get(_secret_key):
            os.environ[_secret_key] = str(st.secrets[_secret_key])
    except Exception:
        pass

# 데모 강제 모드(FOREST_RECO_DEMO=1): 무료 Streamlit Cloud는 시작 시 대용량 번들
# 다운로드(1GB+)와 56만 폴리곤 로딩을 못 버텨 "Oh no"로 죽는다. 이 플래그가 켜지면
# 번들 다운로드를 건너뛰고 가벼운 합성 데이터로만 동작해 항상 안정적으로 작동한다.
# (실데이터 풀 시연은 메모리가 넉넉한 로컬 PC에서.)
_FORCE_DEMO = os.environ.get("FOREST_RECO_DEMO", "").strip().lower() in ("1", "true", "yes", "on")
if _FORCE_DEMO:
    os.environ.pop("FOREST_RECO_DATA_BUNDLE_URL", None)  # 시작 시 대용량 다운로드 차단

# 합성/실데이터 생성을 위한 쓰기 가능한 데이터 폴더(읽기전용 repo 경로 회피)
if (os.environ.get("FOREST_RECO_DATA_BUNDLE_URL") or _FORCE_DEMO) and not os.environ.get("FOREST_RECO_DATA_DIR"):
    os.environ["FOREST_RECO_DATA_DIR"] = str(Path.home() / ".cache" / "forest_reco_data")

# Streamlit Cloud(번들 URL 존재) 무료 플랜은 메모리(~1GB)가 작아, 대용량 토양/상세입지/
# 시업 레이어를 함께 로딩하면 OOM으로 앱이 죽는다("Oh no"). Cloud에서는 경량 모드를
# 기본 적용해 임상도·DEM·강수격자·관측소 실측만 사용한다(로컬은 영향 없음, 풀데이터 유지).
if os.environ.get("FOREST_RECO_DATA_BUNDLE_URL") and not os.environ.get("FOREST_RECO_LIGHT"):
    os.environ["FOREST_RECO_LIGHT"] = "1"

# 배포 식별용 빌드 마커 — Streamlit Cloud가 새 커밋을 실제로 서빙 중인지 확인용.
APP_BUILD = "2026-06-14 v5 demo-mode on Cloud (no bundle download) + fileWatcher=none"

# ---------------------------------------------------------------------------
# 모바일 반응형 스타일
# ---------------------------------------------------------------------------
st.markdown("""
<style>
.block-container {padding-top: .9rem; padding-bottom: 4rem; max-width: 640px;}
h1 {font-size: 2rem !important; letter-spacing:0;}
h2, h3 {letter-spacing:0;}
.stButton>button {width: 100%; height: 3rem; font-size: 1.05rem; border-radius: 12px;
  background: linear-gradient(135deg,#2e7d32,#66bb6a); color:#fff; border:0; font-weight:600;}
.mobile-hero {border:1px solid #dfe8dc; border-radius:8px; padding:14px 16px; margin:4px 0 12px 0;
  background:#fbfdf9;}
.hero-subtitle {font-size:1rem; font-weight:700; color:#225326; margin-bottom:6px;}
.hero-desc {font-size:.92rem; color:#445; line-height:1.55;}
.input-card, .info-card {border:1px solid #e0e0e0; border-radius:8px; padding:12px 14px; margin:10px 0;
  box-shadow:0 1px 3px rgba(0,0,0,.04); background:#fff;}
.info-title {font-size:.82rem; font-weight:700; color:#49624a; margin-bottom:5px;}
.info-value {font-size:.95rem; line-height:1.55; color:#243125;}
.rec-card {border:1px solid #e0e0e0; border-radius:8px; padding:14px 16px; margin:10px 0;
  box-shadow:0 1px 4px rgba(0,0,0,.06); background:#fff; overflow:hidden;}
.rec-head {display:flex; gap:9px; align-items:flex-start;}
.rec-rank {flex:0 0 26px; width:26px; height:26px; line-height:26px; text-align:center;
  border-radius:50%; background:#2e7d32; color:#fff; font-weight:700;}
.rec-title {min-width:0; flex:1;}
.rec-name {display:block; font-size:1.12rem; font-weight:700; color:#1b5e20; line-height:1.25;
  overflow-wrap:anywhere;}
.rec-sci {display:block; color:#666; font-size:.82rem; font-style:italic; line-height:1.35;
  margin-top:2px; overflow-wrap:anywhere;}
.rec-meta {font-size:.85rem; color:#555; line-height:1.45; overflow-wrap:anywhere;}
.score-bar {height:10px; border-radius:6px; background:#eee; overflow:hidden; margin:8px 0;}
.score-fill {height:100%; background:linear-gradient(90deg,#66bb6a,#2e7d32);}
.badge {display:inline-block; background:#e8f5e9; color:#2e7d32; border-radius:8px;
  padding:3px 8px; font-size:.78rem; line-height:1.35; margin:2px 3px 0 0;
  max-width:100%; white-space:normal; overflow-wrap:anywhere; vertical-align:top;}
.badge-warn {background:#fff3e0; color:#e65100;}
.badge-risk {background:#fdecea; color:#a83220;}
.badge-mid {background:#fff8e1; color:#8a5a00;}
.detail-list {margin:4px 0 10px 0;}
.detail-item {border:1px solid #eee; border-radius:8px; padding:9px 10px; margin:6px 0;
  background:#fff; font-size:.9rem; line-height:1.45; overflow-wrap:anywhere;}
.detail-title {font-weight:700; color:#27462a; margin-bottom:2px;}
.explain-box {border:1px solid #e4eadf; border-radius:8px; padding:12px 13px; background:#fbfdf9;
  line-height:1.65; font-size:.95rem; color:#243125; overflow-wrap:anywhere;}
.site-chip {display:inline-block; background:#f1f8e9; border-radius:10px; padding:6px 10px;
  margin:3px; font-size:.9rem;}
.src-badge {display:inline-block; background:#e3f2fd; color:#0d47a1; border-radius:8px;
  padding:3px 9px; font-size:.8rem; margin:2px 4px 2px 0; font-weight:600;}
.src-row {padding:5px 0; font-size:.9rem; border-bottom:1px dashed #eee;}
@media (max-width: 520px) {
  .block-container {padding-left: .75rem; padding-right: .75rem;}
  h1 {font-size: 1.7rem !important;}
  .rec-card {padding:12px 13px;}
  .rec-name {font-size:1.05rem;}
  .badge {font-size:.76rem;}
}
</style>
""", unsafe_allow_html=True)


GANGWON_BOUNDS = {
    "lat_min": 37.0,
    "lat_max": 38.75,
    "lon_min": 127.0,
    "lon_max": 129.7,
}


def _is_gangwon_like(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    return (
        GANGWON_BOUNDS["lat_min"] <= lat <= GANGWON_BOUNDS["lat_max"]
        and GANGWON_BOUNDS["lon_min"] <= lon <= GANGWON_BOUNDS["lon_max"]
    )


def _source_label(source: str | None) -> str:
    return {
        "gps": "현재 위치 GPS",
        "exif": "사진 위치정보",
        "capture_gps": "사진 촬영 시 현재 GPS",
        "upload_gps": "사진 업로드 시 현재 GPS",
        "manual": "직접 입력 좌표",
    }.get(source or "", "미선택")


def _render_info_card(title: str, value: str) -> None:
    st.markdown(
        f"<div class='info-card'><div class='info-title'>{title}</div>"
        f"<div class='info-value'>{value}</div></div>",
        unsafe_allow_html=True,
    )


def _safe_text(value) -> str:
    return html_escape(str(value if value is not None else "-"), quote=True)


def _score_width(score: int | float | None) -> float:
    try:
        return max(0.0, min(100.0, float(score)))
    except (TypeError, ValueError):
        return 0.0


def _score_label(score: int | float | None) -> tuple[str, str]:
    if score is None:
        return "정보 부족", "badge-mid"
    if score >= 75:
        return "높음", "badge"
    if score >= 60:
        return "보통", "badge-mid"
    return "낮음", "badge-warn"


def _reference_sdm_report() -> dict:
    path = ROOT / "forest_reco" / "data" / "sdm_report_current.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# 데이터 소스 (1회 로딩 캐시)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="임상도·DEM 데이터 준비 중…")
def get_sources(use_mock: bool, data_dir: str | None) -> DataSources:
    s = Settings.from_env()
    if data_dir:
        s.data_dir = Path(data_dir)
    src = DataSources(settings=s, use_mock=use_mock)
    # 사전 로딩(첫 질의 지연 방지)
    _ = src.forest
    _ = src.terrain
    _ = src.db
    return src


# ---------------------------------------------------------------------------
# 사이드바: 설정
# ---------------------------------------------------------------------------
def _real_data_exists(d: Path) -> bool:
    """실데이터가 충분히 있을 때만 True.

    Cloud 데모 모드는 51_1.shp와 gangwon_dem.tif를 자동 생성한다. 그 두 파일만 보고
    실데이터로 판단하면 다음 실행에서 51_2.shp를 찾다가 데이터 소스 오류가 난다.
    """
    if (d / ".mock_version").exists():
        return False
    has_dem = (d / "gangwon_dem.tif").exists()
    has_light_forest = (d / "gangwon_forest_light.gpkg").exists()
    has_full_shp_pair = (d / "51_1.shp").exists() and (d / "51_2.shp").exists()
    return has_dem and (has_light_forest or has_full_shp_pair)


@st.cache_resource(show_spinner="배포용 실데이터를 준비하는 중입니다...")
def _prepare_data_bundle(data_dir: str, url: str) -> None:
    from forest_reco.cloud_data import ensure_data_bundle

    ensure_data_bundle(Path(data_dir), url)


_bundle_url = os.environ.get("FOREST_RECO_DATA_BUNDLE_URL")
_bundle_error = None
if _bundle_url:
    try:
        _prepare_data_bundle(str(Settings().data_dir), _bundle_url)
    except Exception as exc:
        _bundle_error = str(exc)

_default_dir = Settings().data_dir
_has_real = (not _FORCE_DEMO) and _real_data_exists(_default_dir)
_ref_sdm = _reference_sdm_report()

with st.sidebar:
    st.header("⚙️ 설정")
    real_dir = st.text_input("실데이터 폴더(임상도/DEM)", value=str(_default_dir),
                             help="gangwon_forest_light.gpkg(또는 51_1.shp), gangwon_dem.tif 등이 있는 폴더. "
                                  "비우면 데모(합성) 데이터 사용.")
    use_mock = st.toggle("데모 모드(합성 데이터)", value=not _has_real,
                         help=("실데이터가 감지되어 실데이터 모드로 시작합니다. 켜면 합성 데이터로 동작."
                               if _has_real else
                               "실데이터가 없을 때 켜세요. 강원권 가상 지형으로 동작합니다."))
    use_sdm = st.toggle("데이터기반 ML(SDM) 사용", value=True,
                        help="관측 수가 충분한 주요 수종의 임상도 실분포를 학습해 추천에 반영합니다. "
                             "희귀 수종은 지식기반 점수와 인접 임분 근거가 함께 보완합니다.")
    gemini_key = st.text_input("Gemini API Key (선택)", type="password",
                               value=os.environ.get("GEMINI_API_KEY", ""),
                               help="입력 시 LLM 설명, 없으면 자동 템플릿 설명.")
    st.caption("© 산림 수종 추천 AI 프로토타입")

st.title("Forest AI")
st.markdown(
    """
<div class="mobile-hero">
  <div class="hero-subtitle">산림 입지분석 기반 적지적수 의사결정 지원 서비스</div>
  <div class="hero-desc">
    GPS 또는 숲 사진의 위치정보를 기반으로 임상도, DEM, 토양, 기후, 조림·관리·병해충 이력을 분석하여
    적합 수종과 관리 방향을 추천합니다.
  </div>
</div>
""",
    unsafe_allow_html=True,
)
st.info("스마트폰에서 더 편하게 사용하려면 브라우저 메뉴에서 “홈 화면에 추가”를 선택해 앱처럼 실행할 수 있습니다.")
st.caption(
    "배포된 https://... 주소에서는 LTE나 다른 와이파이에서도 접속할 수 있고, 카메라·위치 권한이 더 안정적으로 동작합니다. "
    "PC 로컬 주소(http://192.168...)로 테스트할 때만 브라우저 보안 제한이 생길 수 있습니다."
)
st.caption(f"build: {APP_BUILD}")
if _bundle_error:
    st.warning(
        "실데이터를 내려받지 못해 현재는 데모 데이터로 실행됩니다. "
        "Streamlit Secrets의 FOREST_RECO_DATA_BUNDLE_URL 주소를 확인해 주세요."
    )
    with st.expander("실데이터 준비 오류 자세히 보기"):
        st.code(_bundle_error)
elif _bundle_url and not _has_real:
    st.info("실데이터 주소는 설정되어 있지만 아직 실데이터 파일을 찾지 못했습니다. 앱을 재시작하면 다시 준비를 시도합니다.")
elif _has_real:
    st.success("실데이터가 준비되어 데스크탑과 같은 데이터 기준으로 실행 중입니다.")

# ---------------------------------------------------------------------------
# 1) 위치 입력
# ---------------------------------------------------------------------------
st.subheader("📍 1. 위치 입력")
st.caption("아래 3가지 방법 중 하나만 선택하면 됩니다. 마지막으로 성공한 위치가 분석 기준 위치로 저장됩니다.")
tab_gps, tab_gallery, tab_manual = st.tabs(["📍 현재 GPS", "🖼 숲 사진", "✍️ 좌표 입력"])

ss = st.session_state
ss.setdefault("sel_lat", None)
ss.setdefault("sel_lon", None)
ss.setdefault("sel_source", None)
ss.setdefault("browser_lat", None)
ss.setdefault("browser_lon", None)
ss.setdefault("browser_accuracy_m", None)
ss.setdefault("browser_location_status", "waiting")

photo_bytes = None

from forest_reco.exif_gps import extract_gps  # noqa: E402


browser_location_ok = False

with tab_gps:
    st.markdown("<div class='input-card'>브라우저 GPS 자동 수집은 일부 모바일/Cloud 환경에서 화면 오류를 일으킬 수 있어 현재 비활성화했습니다.</div>",
                unsafe_allow_html=True)
    st.info("지도 앱에서 현재 위치의 위도·경도를 복사한 뒤 '좌표 입력' 탭에 붙여넣으면 같은 방식으로 분석할 수 있습니다.")
    st.caption("사진에 위치정보가 남아 있으면 '숲 사진' 탭에서 자동으로 좌표를 읽습니다.")

with tab_gallery:
    st.markdown("<div class='input-card'>현장에서 바로 촬영하거나 원본 사진을 올리면 사진 속 GPS를 먼저 읽고, 없으면 현재 GPS를 함께 사용합니다.</div>",
                unsafe_allow_html=True)
    shot = st.camera_input("현장에서 바로 촬영")
    up = st.file_uploader("또는 숲 사진 업로드", type=["jpg", "jpeg", "png", "heic"])
    photo_source = None
    if shot is not None:
        photo_bytes = shot.getvalue()
        photo_source = "capture"
    elif up is not None:
        photo_bytes = up.getvalue()
        photo_source = "upload"
    if photo_bytes is not None:
        caption = "촬영한 사진" if photo_source == "capture" else "업로드된 사진"
        st.image(photo_bytes, caption=caption, use_container_width=True)
        g = extract_gps(photo_bytes)
        if g.ok:
            acc = f" (정확도 ±{g.accuracy_m:.0f}m)" if g.accuracy_m else ""
            st.success(f"사진 위치정보가 확인되었습니다. 해당 위치를 기준으로 산림 입지분석을 실행합니다.{acc}")
            if ss.sel_source in (None, "exif") or st.button("사진 위치를 분석 위치로 설정"):
                ss.sel_lat = float(g.lat)
                ss.sel_lon = float(g.lon)
                ss.sel_source = "exif"
        else:
            st.warning("사진에서 위치정보를 찾을 수 없습니다.")
            st.info("사진 위치정보가 없으면 '좌표 입력' 탭에서 위도·경도를 직접 입력해주세요.")
    with st.expander("아이폰에서 위치가 안 뜰 때"):
        st.caption(
            "아이폰은 브라우저에서 바로 촬영한 사진의 위치정보를 빼고 전달할 수 있습니다. "
            "사진 EXIF가 없으면 지도 앱에서 현재 위치의 위도·경도를 복사해 '좌표 입력' 탭에 넣어주세요. "
            "로컬 모바일 주소(http://192.168...)에서는 보안 제한 때문에 카메라나 GPS 권한이 막힐 수 있습니다."
        )

with tab_manual:
    st.markdown("<div class='input-card'>지도 앱이나 현장 기록에서 확인한 위도·경도를 직접 입력합니다.</div>",
                unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    _dlat = float(ss.sel_lat) if (ss.sel_source == "manual" and ss.sel_lat is not None) else 37.704054
    _dlon = float(ss.sel_lon) if (ss.sel_source == "manual" and ss.sel_lon is not None) else 128.330231
    mlat = c1.number_input("위도", value=_dlat, format="%.6f")
    mlon = c2.number_input("경도", value=_dlon, format="%.6f")
    if st.button("이 좌표를 분석 위치로 설정"):
        if not (-90 <= mlat <= 90 and -180 <= mlon <= 180):
            st.error("위도는 -90~90, 경도는 -180~180 사이로 입력해주세요.")
        else:
            ss.sel_lat = float(mlat)
            ss.sel_lon = float(mlon)
            ss.sel_source = "manual"
            st.success("직접 입력한 좌표를 분석 기준 위치로 저장했습니다.")

lat = ss.sel_lat
lon = ss.sel_lon
loc_source = ss.sel_source

if lat is not None and lon is not None:
    in_gangwon = _is_gangwon_like(lat, lon)
    region_msg = "강원도 분석 범위 안" if in_gangwon else "현재 프로토타입은 강원도 지역 분석을 기준으로 합니다."
    _render_info_card(
        "분석 기준 위치",
        f"{_source_label(loc_source)}<br>위도 {lat:.6f}, 경도 {lon:.6f}<br>{region_msg}",
    )
    if not in_gangwon and not use_mock:
        st.warning("현재 프로토타입은 강원도 지역 분석을 기준으로 합니다.")
else:
    _render_info_card("분석 기준 위치", "아직 위치가 선택되지 않았습니다. GPS, 숲 사진, 좌표 입력 중 하나를 선택해주세요.")

# ---------------------------------------------------------------------------
# 2) 식재 목적 / 독자
# ---------------------------------------------------------------------------
st.subheader("🎯 2. 식재 목적 · 설명 대상")
c1, c2 = st.columns(2)
goal = c1.selectbox("식재 목적", ["(자동)"] + list(GOALS.keys()), index=0)
goal = None if goal == "(자동)" else goal
audience = c2.selectbox("설명 대상", list(AUDIENCES.keys()), index=0)

# 위치 지도 미리보기
# 주의: st.map(deck.gl/WebGL)은 잦은 rerun·expander 토글 시 React 노드를 놓쳐
# "Failed to execute 'removeChild' on 'Node'" 프론트 오류를 유발할 수 있어
# WebGL 없는 정적 지도 링크로 대체한다.
if lat is not None and lon is not None:
    _osm = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=13/{lat}/{lon}"
    st.markdown(
        f"📍 선택 위치: 위도 **{lat:.6f}**, 경도 **{lon:.6f}** · "
        f"[지도에서 열기]({_osm})"
    )

# ---------------------------------------------------------------------------
# 3) 분석 실행
# ---------------------------------------------------------------------------
run = st.button("🌳 적합 수종 분석하기")

if run:
    if lat is None or lon is None:
        st.error("먼저 위치를 입력하세요 (사진/GPS/좌표 중 하나).")
    elif not use_mock and not _is_gangwon_like(lat, lon):
        st.error("현재 프로토타입은 강원도 지역 분석을 기준으로 합니다.")
    else:
        sources = get_sources(use_mock, real_dir if (real_dir and not use_mock) else None)
        with st.spinner("입지 분석 및 수종 추천 중… (ML 최초 사용 시 모델 학습으로 수십 초 소요)"):
            res = analyze(lat=lat, lon=lon, goal=goal, audience=audience,
                          sources=sources, gemini_api_key=(gemini_key or None),
                          top_k=6, use_sdm=use_sdm)
            if isinstance(res, dict) and isinstance(res.get("location"), dict):
                res["location"]["source"] = loc_source
        st.session_state["last_result"] = res

# 결과 표시 — 세션에 저장된 결과를 사용해 rerun(탭·설정 변경) 후에도 유지된다.
res = st.session_state.get("last_result")
if res is not None and not res.get("ok"):
    st.error(res.get("message", "분석에 실패했습니다."))
    res = None

if res is not None:
    c_info, c_clear = st.columns([3, 1])
    c_info.caption("결과는 새로 분석하기 전까지 유지됩니다.")
    if c_clear.button("🔄 초기화"):
        st.session_state.pop("last_result", None)
        st.rerun()

    # --- 분석 위치 ---
    loc = res.get("location") or {}
    rlat = loc.get("lat")
    rlon = loc.get("lon")
    if rlat is not None and rlon is not None:
        st.subheader("📍 분석 위치")
        _render_info_card(
            "기준 좌표",
            f"{_source_label(loc.get('source') or loc_source)}<br>"
            f"위도 {float(rlat):.6f}, 경도 {float(rlon):.6f}<br>"
            "500m · 1km · 3km 반경 이력은 아래 관리/병해충 분석에 반영됩니다.",
        )

    # --- 입지 요약 ---
    s = res["site"]
    st.subheader("🗻 입지 분석")
    chips = [
        f"기후대 <b>{s['climate_zone']}</b>",
        f"고도 <b>{s['elevation_m']}m</b>",
        f"경사 <b>{s['slope_deg']}°</b>" if s['slope_deg'] is not None else "경사 -",
        f"향 <b>{s['aspect_dir']}</b>",
        f"온량지수≈<b>{int(s['warmth_index'])}</b>",
    ]
    _oc = res.get("observed_climate")
    if _oc and _oc.get("temp_c") is not None:
        chips.append(f"실측기온 <b>{_oc['temp_c']:.1f}℃</b>")
        chips.append(f"실측강수 <b>{_oc['precip_mm']:.0f}mm</b>")
    _pg = res.get("precip_grid")
    if _pg and _pg.get("annual_mean_mm") is not None:
        chips.append(f"격자강수 <b>{_pg['annual_mean_mm']:.0f}mm</b>")
    st.markdown(" ".join(f"<span class='site-chip'>{c}</span>" for c in chips), unsafe_allow_html=True)
    fi = res.get("forest_info")
    if fi:
        nearest = " (인접 임분 참조)" if res.get("forest_nearest") else ""
        st.caption(f"현장 임상{nearest}: {fi.get('임종','-')} · 수종 {fi.get('수종','-')} · "
                   f"{fi.get('경급','-')} · {fi.get('영급','-')} · 밀도 {fi.get('밀도','-')}")
    si = res.get("site_info")
    if si:
        nearest = " (인접 입지 참조)" if res.get("site_nearest") else ""
        st.caption(
            f"산림입지{nearest}: 토심 {si.get('토심코드','-')} · 토성 {si.get('토성코드','-')} · "
            f"토양형 {si.get('토양형코드','-')} · 모암 {si.get('모암_대분류','-')}/{si.get('모암_중분류','-')} · "
            f"지형군 {si.get('지형군코드','-')}"
        )
    sdi = res.get("site_detail_info")
    if sdi:
        nearest = " (인접 상세입지 참조)" if res.get("site_detail_nearest") else ""
        st.caption(
            f"상세 산림입지{nearest}: 배수 {sdi.get('토양배수코드','-')} · 유효토심 {sdi.get('유효토심','-')} · "
            f"암석노출 {sdi.get('암석노출도','-')} · 능선/계곡 {sdi.get('능선계곡코드','-')} · "
            f"수분영향 {sdi.get('수분영향도','-')}"
        )

    # --- 분석에 사용한 산림 공공데이터(데이터 활용 가시화) ---
    nsp = res.get("neighborhood_species") or {}
    used = []
    if fi:
        used.append(("🗺 국가 수치임상도",
                     "현장 임분(임종·수종·경급·영급·밀도)"
                     + (f" + 인접 {len(nsp)}종 분포" if nsp else "")))
    if s.get("elevation_m") is not None:
        used.append(("⛰ 수치표고모델(DEM)", "고도·경사·향 산출"))
    if si:
        used.append(("🧱 산림입지도",
                     f"토심 {si.get('토심코드','-')} · 토성 {si.get('토성코드','-')} · "
                     f"모암 {si.get('모암_대분류','-')}/{si.get('모암_중분류','-')} · 지형군 {si.get('지형군코드','-')}"))
    if sdi:
        used.append(("🧪 상세 산림입지/토양도",
                     f"배수 {sdi.get('토양배수코드','-')} · 유효토심 {sdi.get('유효토심','-')} · "
                     f"암석노출 {sdi.get('암석노출도','-')} · 수분영향 {sdi.get('수분영향도','-')}"))
    if s.get("climate_zone"):
        used.append(("🌡 기후대 추정", "위도·고도 기반 온량지수/기후대"))
    oc = res.get("observed_climate")
    if oc and oc.get("temp_c") is not None:
        used.append(("🌦 산악기상관측소 실측(149개소)",
                     f"주변 {oc.get('n_used', '?')}개 관측소 IDW 보간"
                     f"(최근접 {oc.get('nearest_km', '?')}km) · "
                     f"기온 {oc['temp_c']:.1f}℃ · 강수 {oc['precip_mm']:.0f}mm (SDM 피처)"))
    pg = res.get("precip_grid")
    if pg and pg.get("annual_mean_mm") is not None:
        used.append(("🌧 WorldClim/CRU 강수 격자(2020~2024)",
                     f"연평균 {pg['annual_mean_mm']:.0f}mm · 생육기 {pg['growing_may_sep_mm']:.0f}mm · "
                     f"여름 {pg['summer_jun_aug_mm']:.0f}mm · 겨울 {pg['winter_dec_feb_mm']:.0f}mm"))
    mg = res.get("management_info") or {}
    if mg:
        p = mg.get("planting") or {}
        t = mg.get("tending") or {}
        d = mg.get("disease") or {}
        bits = []
        if p:
            bits.append(f"조림 {p.get('year', '?')}년 {p.get('species', '')}")
        if t:
            bits.append(f"숲가꾸기 {t.get('year', '?')}년 {t.get('work_type', '')}")
        if d:
            bits.append(f"병해충 1km {d.get('count_1km', 0)}건")
        used.append(("산림경영 이력", " · ".join(bits) if bits else "조림·숲가꾸기·병해충 이력"))
    if res.get("sdm_used"):
        used.append(("🤖 데이터기반 ML(SDM)",
                     f"주요 수종 임상도 실분포 학습 · 상위3 적중률 "
                     f"{(res.get('sdm_top3') or 0):.0%}(f1={res.get('sdm_quality')})"))
    if used:
        st.markdown(
            "분석 근거 데이터: "
            + "".join(f"<span class='src-badge'>{n}</span>" for n, _ in used),
            unsafe_allow_html=True)
        with st.expander("📊 어떤 데이터로 무엇을 판단했나 (자세히)"):
            for name, desc in used:
                st.markdown(f"<div class='src-row'><b>{name}</b> — {desc}</div>",
                            unsafe_allow_html=True)
            st.caption("출처: 국가 수치임상도·수치표고모델(DEM) 등 산림 공공·빅데이터 "
                       "(국립산림과학원 산림과학지식서비스 등)")

    # 강원 전역 기후 분포(149개 관측소 IDW 보간) — 점 데이터를 전역 면으로 활용했음을 시각화
    from pathlib import Path as _P
    _mt = _P(real_dir) / "climate_map_temp_c.png"
    _mp = _P(real_dir) / "climate_map_precip_mm.png"
    if _mt.exists() or _mp.exists():
        with st.expander("🗺 강원 전역 기후 분포 (149개 관측소 IDW 보간)"):
            st.caption("산악기상관측소 149개 실측값을 IDW로 강원 전역에 보간. "
                       "흰 점=관측소, 파랑=저온/소우·빨강=고온/다우(고산지대가 차갑게 나타남).")
            if _mt.exists():
                st.image(str(_mt), caption="연평균 기온 분포(보간)", use_container_width=True)
            if _mp.exists():
                st.image(str(_mp), caption="강수 분포(보간)", use_container_width=True)

    # --- 현재 숲 진단 (기존 임분 평가) ---
    diag = res.get("diagnosis")
    if diag:
        st.subheader("🩺 현재 숲 진단")
        def _color(v):
            return {"높음": "🔴", "매우 높음": "🔴", "보통": "🟡", "낮음": "🟢"}.get(v, "⚪")
        d1, d2, d3 = st.columns(3)
        d1.metric("생육 적합도", f"{_color(diag['생육_적합도'])} {diag['생육_적합도']}")
        d2.metric("병해충 취약도", f"{_color(diag['병해충_취약도'])} {diag['병해충_취약도']}")
        d3.metric("관리 우선순위", f"{_color(diag['관리_우선순위'])} {diag['관리_우선순위']}")
        if diag.get("근거"):
            st.caption("· " + "  · ".join(diag["근거"][:4]))
        st.caption("※ 위 진단은 현재 자라는 숲의 상태 평가입니다(아래 '추천 수종'은 새로 심을 나무).")

    # --- 반경 기반 관리/병해충 분석 ---
    radius = res.get("management_radius") or {}
    if radius:
        st.subheader("🧭 반경 기반 이력 분석")
        st.caption("좌표를 미터 단위 좌표계로 변환한 뒤 500m, 1km, 3km 반경을 계산했습니다.")

        def _radius_line(label, data, key):
            item = (data or {}).get(key, {}) or {}
            return f"{label}: {item.get('count', 0)}건"

        d = radius.get("disease") or {}
        p = radius.get("planting") or {}
        t = radius.get("tending") or {}
        c1, c2, c3 = st.columns(3)
        c1.metric("병해충 500m", f"{(d.get('500') or {}).get('count', 0)}건")
        c2.metric("병해충 1km", f"{(d.get('1000') or {}).get('count', 0)}건")
        c3.metric("병해충 3km", f"{(d.get('3000') or {}).get('count', 0)}건")
        with st.expander("조림·숲가꾸기·병해충 반경 분석 자세히"):
            st.markdown("**병해충 이력**")
            st.write(" · ".join(_radius_line(r, d, k) for r, k in [("500m", "500"), ("1km", "1000"), ("3km", "3000")]))
            nearest = next((x.get("nearest_m") for x in [d.get("500", {}), d.get("1000", {}), d.get("3000", {})] if x.get("nearest_m") is not None), None)
            st.caption(f"가장 가까운 병해충 발생지 거리: {nearest}m" if nearest is not None else "반경 3km 내 병해충 발생 이력 없음")
            st.markdown("**조림 이력**")
            for k, label in [("500", "500m"), ("1000", "1km"), ("3000", "3km")]:
                item = p.get(k, {}) or {}
                st.caption(f"{label}: {item.get('count', 0)}건 · 주요 조림수종 {item.get('main_species', '정보 없음')} · 최근 {item.get('latest_year', '정보 없음')}")
            st.markdown("**숲가꾸기 이력**")
            for k, label in [("500", "500m"), ("1000", "1km"), ("3000", "3km")]:
                item = t.get(k, {}) or {}
                st.caption(f"{label}: {item.get('count', 0)}건 · 주요 작업 {item.get('main_work_type', '정보 없음')} · 최근 {item.get('latest_year', '정보 없음')}")

    # --- 추천 수종 카드 ---
    st.subheader("🌱 추천 수종")
    if res.get("sdm_used"):
        q = res.get("sdm_quality")
        top3 = res.get("sdm_top3")
        primary_top3 = res.get("sdm_primary_top3")
        boosted = res.get("sdm_top3_boosted")
        ncls = res.get("sdm_n_classes")
        if isinstance(top3, (int, float)):
            label = "Top-3 강화" if boosted else "Top-3"
            top3txt = f" · {label} {top3:.0%}"
            if boosted and isinstance(primary_top3, (int, float)):
                top3txt += f"(기본 {primary_top3:.0%})"
        else:
            top3txt = ""
        clstxt = f" · 학습수종 {ncls}종" if ncls else ""
        st.caption(f"🤖 데이터기반 ML(SDM) 반영됨 · 주요 수종 기준 f1={q}{top3txt}{clstxt} · "
                   f"적용 가중치={res.get('sdm_weight_applied')}/100 "
                   f"(희귀 수종은 지식기반·인접 임분 근거로 보완)")
    else:
        st.caption("📐 지식기반 적지적수 점수로 추천(ML 미사용 또는 데이터 부족)")
    if use_mock and _ref_sdm:
        ref_top3 = _ref_sdm.get("top3_accuracy")
        ref_top3_txt = f"{ref_top3:.0%}" if isinstance(ref_top3, (int, float)) else "-"
        st.caption(
            f"현재 배포판은 데모 데이터 기준입니다. 데스크탑 실데이터 기준 참고 성능: "
            f"f1={_ref_sdm.get('f1_macro')} · Top-3={ref_top3_txt} "
            f"· 학습수종 {_ref_sdm.get('n_classes')}종"
        )
    if not res["recommendations"]:
        st.warning("이 입지에 부합하는 추천 수종을 찾지 못했습니다.")
    for i, r in enumerate(res["recommendations"], 1):
        reasons = "".join(f"<span class='badge'>{_safe_text(x)}</span>" for x in r["주요근거"][:3])
        warns = "".join(f"<span class='badge badge-warn'>주의: {_safe_text(x)}</span>" for x in r.get("유의사항", [])[:2])
        confidence, confidence_class = _score_label(r.get("적합점수"))
        pest_risk = "주의" if any("병해충" in x for x in r.get("유의사항", [])) else "보통"
        pest_class = "badge-risk" if pest_risk == "주의" else "badge"
        rec_badges = (
            f"<span class='badge {confidence_class}'>추천 신뢰도 {confidence}</span>"
            f"<span class='badge {pest_class}'>병해충 위험도 {pest_risk}</span>"
        )
        score_width = _score_width(r.get("적합점수"))
        st.markdown(f"""
<div class="rec-card">
  <div class="rec-head">
    <span class="rec-rank">{i}</span>
    <div class="rec-title">
      <span class="rec-name">{_safe_text(r['수종'])}</span>
      <span class="rec-sci">{_safe_text(r['학명'])}</span>
    </div>
  </div>
  <div class="score-bar"><div class="score-fill" style="width:{score_width}%"></div></div>
  <div class="rec-meta">적합점수 <b>{_safe_text(r['적합점수'])}</b> · 탄소흡수 {_safe_text(r['탄소흡수'])} · {_safe_text(r['유형'])}</div>
  <div style="margin-top:6px;">{rec_badges}</div>
  <div style="margin-top:6px;">{reasons}</div>
  <div style="margin-top:4px;">{warns}</div>
</div>""", unsafe_allow_html=True)
        with st.expander(f"{r['수종']}를 추천한 이유 자세히"):
            st.markdown("**점수 세부 항목**")
            detail_rows = []
            for f in r.get("점수세부", []):
                detail_rows.append({
                    "항목": f.get("항목"),
                    "점수": f.get("점수"),
                    "가중치": f.get("가중치"),
                    "근거": f.get("근거"),
                })
            if detail_rows:
                detail_html = "".join(
                    "<div class='detail-item'>"
                    f"<div class='detail-title'>{_safe_text(row.get('항목'))} "
                    f"{_safe_text(row.get('점수'))}점</div>"
                    f"<div>가중치 {_safe_text(row.get('가중치'))} · {_safe_text(row.get('근거'))}</div>"
                    "</div>"
                    for row in detail_rows
                )
                st.markdown(f"<div class='detail-list'>{detail_html}</div>", unsafe_allow_html=True)
            else:
                st.caption("점수 세부 정보 없음")
            st.markdown("**긍정 근거**")
            positives = r.get("주요근거") or ["확인된 긍정 근거 정보 없음"]
            for item in positives:
                st.caption(f"· {item}")
            st.markdown("**감점 요인**")
            cautions = r.get("유의사항") or ["뚜렷한 감점 요인은 확인하지 않았습니다."]
            for item in cautions:
                st.caption(f"· {item}")
            st.markdown("**관리 주의사항**")
            st.caption("· 식재 전 현장 토심·배수·사면 방향을 재확인하세요.")
            st.caption("· 병해충 발생 이력이 있는 지역은 초기 모니터링을 강화하세요.")
            st.caption("· 최근 조림·숲가꾸기 이력과 충돌하지 않도록 관리 계획을 확인하세요.")

    # --- LLM/폴백 설명 ---
    st.subheader("📝 AI 설명")
    ex = res["explanation"]
    tag = "Gemini" if ex["source"] == "gemini" else "자동 요약(오프라인)"
    st.caption(f"설명 출처: {tag}")
    explanation_html = "<br>".join(_safe_text(line) for line in str(ex.get("text", "")).splitlines())
    st.markdown(f"<div class='explain-box'>{explanation_html}</div>", unsafe_allow_html=True)

    st.subheader("📈 검증 지표")
    try:
        sources_for_validation = get_sources(use_mock, real_dir if (real_dir and not use_mock) else None)
        metrics = evaluate_validation(Path(real_dir), analyze, sources_for_validation)
        if metrics.get("available"):
            m1, m2, m3 = st.columns(3)
            m1.metric("Top-1 Accuracy", metrics["top1_accuracy"])
            m2.metric("Macro F1-score", metrics["macro_f1"])
            m3.metric("Top-3 Accuracy", metrics["top3_accuracy"])
            st.caption(f"검증 데이터: {metrics.get('file')} · 표본 {metrics.get('n')}건")
        else:
            st.info(metrics.get("message"))
            st.caption("검증 데이터 파일명: validation_data.csv · 필요 컬럼: lat, lon, true_species")
    except Exception as e:
        st.info("검증 지표 계산 중 오류가 발생해 기본 분석 결과만 표시합니다.")
        st.caption(str(e))

    st.subheader("📄 AI 요약 보고서")
    html_report = create_report(res)
    st.download_button(
        "HTML 보고서 다운로드",
        data=html_report.encode("utf-8"),
        file_name=report_filename("html"),
        mime="text/html",
        use_container_width=True,
    )
    try:
        pdf_report = create_pdf_report(res)
        st.download_button(
            "PDF 보고서 다운로드",
            data=pdf_report,
            file_name=report_filename("pdf"),
            mime="application/pdf",
            use_container_width=True,
        )
    except Exception as e:
        st.info("PDF 보고서 생성에 필요한 환경이 준비되지 않아 HTML 보고서만 제공합니다.")
        st.caption(str(e))

    with st.expander("🔬 상세 데이터 (연구자/공무원용)"):
        st.json(res)
