"""
config.py — 경로/좌표계 상수 및 환경 설정

원본 노트북은 ``/content/drive/MyDrive/Forest_AI/...`` 경로가 코드 곳곳에
하드코딩되어 Colab 밖에서는 전혀 동작하지 않았다. 여기서는 모든 경로/설정을
한 곳에 모으고, 환경변수로 덮어쓸 수 있게 하여 Colab·로컬·서버 어디서든
동작하도록 한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 좌표계 상수
# ---------------------------------------------------------------------------
# WGS84: GPS / 휴대폰 사진 EXIF가 사용하는 위경도 좌표계
CRS_WGS84 = "EPSG:4326"
# Korea 2000 / Unified CS (UTM-K). 국가 수치임상도(임상도)의 표준 좌표계.
# (원본 노트북도 forest.crs == EPSG:5179 를 전제로 to_crs(forest.crs)를 호출했다)
CRS_KOREA_TM = "EPSG:5179"


def _detect_base_dir() -> Path:
    """Colab(드라이브 마운트) 환경이면 드라이브 경로, 아니면 패키지 옆 data 폴더."""
    env = os.environ.get("FOREST_RECO_DATA_DIR")
    if env:
        return Path(env)
    drive = Path("/content/drive/MyDrive/Forest_AI/data")
    if drive.exists():
        return drive
    # 로컬 기본값: 이 파일 기준 ../data
    return Path(__file__).resolve().parent.parent / "data"


@dataclass
class Settings:
    """런타임 설정. 환경변수로 덮어쓸 수 있다."""

    data_dir: Path = field(default_factory=_detect_base_dir)

    # 임상도 shp 파일명(여러 개를 concat). 실제 데이터 파일명에 맞춰 조정.
    forest_shapefiles: tuple[str, ...] = ("51_1.shp", "51_2.shp")
    # 경량 GeoPackage(scripts/prepare_forest_data.py 산출물). data_dir에 있으면
    # shp 대신 이걸 우선 로딩한다(원본 2GB → ~174MB, 로딩·질의 훨씬 빠름).
    light_gpkg_name: str = "gangwon_forest_light.gpkg"
    prefer_light_gpkg: bool = True
    # DEM 래스터 파일명
    dem_filename: str = "gangwon_dem.tif"
    # 산림입지도(토양·모암·토심·토성 등 입지 속성) 경량 GeoPackage.
    site_gpkg_name: str = "gangwon_site_light.gpkg"
    # 상세 산림입지/토양 속성(TB_FGDI_FS_IJ100 경량화본).
    site_detail_gpkg_name: str = "gangwon_site_detail_light.gpkg"
    # WorldClim/CRU 2020~2024 강수량 경량 래스터.
    precip_filename: str = "gangwon_precip_2020_2024.tif"
    planting_gpkg_name: str = "gangwon_planting_light.gpkg"
    tending_gpkg_name: str = "gangwon_tending_light.gpkg"
    disease_gpkg_name: str = "gangwon_disease_points_light.gpkg"

    # 임상도 좌표계 (파일에 .prj가 없을 때의 폴백)
    forest_crs_fallback: str = CRS_KOREA_TM

    # 위치가 임상도 폴리곤 밖일 때, 이 거리(m) 내 가장 가까운 임분을 참고용으로 사용
    nearest_search_radius_m: float = 500.0
    # 인접 경험적 수종 빈도를 집계할 반경(m)
    neighborhood_radius_m: float = 1000.0

    # Gemini
    gemini_model: str = "gemini-2.5-flash"
    gemini_api_key_env: str = "GEMINI_API_KEY"

    # 수종 지식베이스 JSON (없으면 패키지 내장 기본 KB 사용)
    species_db_path: Path | None = None

    # 산악기상관측소 실측 기후(stations.csv). 있으면 SDM 기후피처·기후 표시에 사용.
    stations_filename: str = "stations.csv"

    # 수종분포모델(SDM) 저장/로딩 경로(.joblib). 지정 시 1회 학습 후 재사용.
    sdm_path: Path | None = None
    # SDM 알고리즘. 현재 데이터 실험 기준 RF가 f1/top-3 균형이 가장 좋다.
    # ("hgb","rf")처럼 여러 개를 지정하면 확률 평균 앙상블로 동작한다.
    sdm_algos: tuple = ("rf",)
    # SDM 학습 표본 수 / 상위 N종 제한(롱테일 완화).
    # 실데이터 기준 상위 5종은 f1_macro와 top-3가 가장 안정적이다.
    # 나머지 희귀/저빈도 수종은 지식기반 적지적수와 인접 임분 근거가 보완한다.
    sdm_n_samples: int = 8000
    sdm_top_species: int = 5
    use_management_in_sdm: bool = False
    use_top3_boost_sdm: bool = True
    # 경량 모드: 대용량 토양/상세입지/시업 레이어를 로딩하지 않는다(저메모리 Cloud용).
    # 임상도·DEM·강수격자·관측소 실측만 사용해 메모리 폭주(OOM)를 방지한다.
    light_mode: bool = False

    # ---- 파생 경로 ----
    @property
    def dem_path(self) -> Path:
        return self.data_dir / self.dem_filename

    @property
    def site_path(self) -> Path:
        return self.data_dir / self.site_gpkg_name

    @property
    def site_detail_path(self) -> Path:
        return self.data_dir / self.site_detail_gpkg_name

    @property
    def precip_path(self) -> Path:
        return self.data_dir / self.precip_filename

    @property
    def planting_path(self) -> Path:
        return self.data_dir / self.planting_gpkg_name

    @property
    def tending_path(self) -> Path:
        return self.data_dir / self.tending_gpkg_name

    @property
    def disease_path(self) -> Path:
        return self.data_dir / self.disease_gpkg_name

    @property
    def stations_path(self) -> Path:
        verified = self.data_dir / "derived" / "stations_verified.csv"
        if verified.exists():
            return verified
        return self.data_dir / self.stations_filename

    @property
    def raw_stations_path(self) -> Path:
        return self.data_dir / self.stations_filename

    def forest_paths(self) -> list[Path]:
        # 경량 gpkg가 있으면 우선 사용(환경변수 FOREST_RECO_SHP로 명시하면 그게 최우선).
        if self.prefer_light_gpkg:
            light = self.data_dir / self.light_gpkg_name
            if light.exists():
                return [light]
        return [self.data_dir / name for name in self.forest_shapefiles]

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls()
        if v := os.environ.get("FOREST_RECO_DEM"):
            s.dem_filename = v
        if v := os.environ.get("FOREST_RECO_SHP"):
            s.forest_shapefiles = tuple(p.strip() for p in v.split(",") if p.strip())
            s.prefer_light_gpkg = False  # 명시 지정이 경량 gpkg 자동선택보다 우선
        if v := os.environ.get("FOREST_RECO_SPECIES_DB"):
            s.species_db_path = Path(v)
        if v := os.environ.get("FOREST_RECO_SDM_ALGOS"):
            s.sdm_algos = tuple(a.strip() for a in v.split(",") if a.strip())
        if v := os.environ.get("FOREST_RECO_GEMINI_MODEL"):
            s.gemini_model = v
        if os.environ.get("FOREST_RECO_LIGHT", "").strip().lower() in ("1", "true", "yes", "on"):
            s.light_mode = True
            s.use_top3_boost_sdm = False  # 2차 모델 학습도 생략(메모리·시간 절약)
        return s


# 기본 싱글턴 — 필요 시 호출부에서 별도 Settings를 만들어 주입 가능
SETTINGS = Settings.from_env()
