"""
pipeline.py — end-to-end 분석 파이프라인

  사진(EXIF) 또는 위경도
    → 임상도/DEM 적재(지연·캐시)
    → 입지 질의(임분 + 고도/경사/향)
    → 기후대 판정
    → 인접 경험적 수종 빈도
    → 식재 적합 수종 추천
    → Gemini/폴백 자연어 설명
    → 구조화 결과 dict

실데이터가 없으면 자동으로 합성 데이터(mockdata)를 생성해 동작한다(use_mock).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import SETTINGS, Settings, CRS_WGS84
from .exif_gps import extract_gps, GpsResult
from .forest_map import ForestMap
from .site_map import SiteMap
from .site_detail_map import SiteDetailMap
from .precip_raster import PrecipRaster
from .management_map import ManagementLayers
from .afforestation_map import AfforestationMap
from .forest_function_map import ForestFunctionMap
from .landslide_raster import LandslideRaster
from .terrain import Terrain
from .climate import classify_zone
from .recommender import SiteContext, recommend, GOALS
from .diagnosis import diagnose_stand
from .species_db import SpeciesDB, default_db
from .llm import generate_explanation


@dataclass
class DataSources:
    """임상도/DEM 자원 보관(지연 로딩 + 캐시)."""
    settings: Settings = field(default_factory=lambda: SETTINGS)
    use_mock: bool = False
    _forest: Optional[ForestMap] = None
    _terrain: Optional[Terrain] = None
    _db: Optional[SpeciesDB] = None
    _sdm: object = None
    _sdm_tried: bool = False
    _sdm_top3: object = None
    _sdm_top3_tried: bool = False
    _observed: object = None
    _observed_tried: bool = False
    _site: Optional[SiteMap] = None
    _site_tried: bool = False
    _site_detail: Optional[SiteDetailMap] = None
    _site_detail_tried: bool = False
    _precip: Optional[PrecipRaster] = None
    _precip_tried: bool = False
    _management: Optional[ManagementLayers] = None
    _management_tried: bool = False
    _afforestation: object = None
    _afforestation_tried: bool = False
    _forest_function: object = None
    _forest_function_tried: bool = False
    _landslide: object = None
    _landslide_tried: bool = False

    def _maybe_make_mock(self):
        from .mockdata import ensure_mock_dataset
        ensure_mock_dataset(self.settings.data_dir)

    @property
    def forest(self) -> ForestMap:
        if self._forest is None:
            if self.use_mock:
                self._maybe_make_mock()
                self._forest = ForestMap.load(
                    [self.settings.data_dir / "51_1.shp"], settings=self.settings)
            else:
                self._forest = ForestMap.load(settings=self.settings)
        return self._forest

    @property
    def terrain(self) -> Terrain:
        if self._terrain is None:
            if self.use_mock:
                self._maybe_make_mock()
            self._terrain = Terrain.load(settings=self.settings)
        return self._terrain

    @property
    def site(self) -> Optional[SiteMap]:
        """산림입지도(토양·모암·토심·토성) 지연 로딩. 없으면 None."""
        if getattr(self.settings, "light_mode", False):
            return None  # 경량 모드: 대용량(274MB) 토양도 미로딩
        if self._site is None and not self._site_tried:
            self._site_tried = True
            try:
                self._site = SiteMap.load(settings=self.settings)
            except Exception:  # noqa: BLE001 - 보조 데이터이므로 실패해도 계속
                self._site = None
        return self._site

    @property
    def site_detail(self) -> Optional[SiteDetailMap]:
        """상세 산림입지/토양도 지연 로딩. 없으면 None."""
        if getattr(self.settings, "light_mode", False):
            return None  # 경량 모드: 최대용량(537MB) 상세입지도 미로딩
        if self._site_detail is None and not self._site_detail_tried:
            self._site_detail_tried = True
            try:
                self._site_detail = SiteDetailMap.load(settings=self.settings)
            except Exception:  # noqa: BLE001
                self._site_detail = None
        return self._site_detail

    @property
    def precip(self) -> Optional[PrecipRaster]:
        """WorldClim/CRU 2020~2024 강수량 격자 지연 로딩. 없으면 None."""
        if self._precip is None and not self._precip_tried:
            self._precip_tried = True
            try:
                self._precip = PrecipRaster.load(settings=self.settings)
            except Exception:  # noqa: BLE001
                self._precip = None
        return self._precip

    @property
    def management(self) -> Optional[ManagementLayers]:
        if getattr(self.settings, "light_mode", False):
            return None  # 경량 모드: 시업이력(병해충 14만점 등) 미로딩
        if self._management is None and not self._management_tried:
            self._management_tried = True
            try:
                self._management = ManagementLayers.load(settings=self.settings)
            except Exception:  # noqa: BLE001
                self._management = None
        return self._management

    @property
    def afforestation(self):
        """맞춤형조림지도(공식 추천수종) 지연 로딩. light_mode/없으면 None."""
        if getattr(self.settings, "light_mode", False):
            return None
        if self._afforestation is None and not self._afforestation_tried:
            self._afforestation_tried = True
            try:
                self._afforestation = AfforestationMap.load(settings=self.settings)
            except Exception:  # noqa: BLE001
                self._afforestation = None
        return self._afforestation

    @property
    def forest_function(self):
        """산림기능구분도 지연 로딩. light_mode/없으면 None."""
        if getattr(self.settings, "light_mode", False):
            return None
        if self._forest_function is None and not self._forest_function_tried:
            self._forest_function_tried = True
            try:
                self._forest_function = ForestFunctionMap.load(settings=self.settings)
            except Exception:  # noqa: BLE001
                self._forest_function = None
        return self._forest_function

    @property
    def landslide(self):
        """산사태위험지도(window read) 지연 로딩. light_mode/없으면 None."""
        if getattr(self.settings, "light_mode", False):
            return None
        if self._landslide is None and not self._landslide_tried:
            self._landslide_tried = True
            try:
                self._landslide = LandslideRaster.load(settings=self.settings)
            except Exception:  # noqa: BLE001
                self._landslide = None
        return self._landslide

    @property
    def db(self) -> SpeciesDB:
        if self._db is None:
            self._db = SpeciesDB.load(self.settings.species_db_path) \
                if self.settings.species_db_path else default_db()
        return self._db

    @property
    def observed(self):
        """산악기상관측소 실측 기후(stations.csv, 지연 로딩). 없으면 None."""
        if self._observed is None and not self._observed_tried:
            self._observed_tried = True
            try:
                from .observed_climate import ObservedClimate
                self._observed = ObservedClimate.from_csv(self.settings.stations_path)
            except Exception:  # noqa: BLE001 - 보조 데이터이므로 실패해도 계속
                self._observed = None
        return self._observed

    @property
    def sdm(self):
        """수종분포모델(지연 학습/로딩, 1회 캐시). 실패 시 None."""
        if self._sdm is None and not self._sdm_tried:
            self._sdm_tried = True
            from .sdm import SpeciesDistributionModel
            path = getattr(self.settings, "sdm_path", None)
            try:
                if path and Path(path).exists():
                    self._sdm = SpeciesDistributionModel.load(path)
                else:
                    self._sdm = SpeciesDistributionModel.train(
                        self.forest, self.terrain,
                        algos=getattr(self.settings, "sdm_algos", ("hgb",)),
                        n_samples=getattr(self.settings, "sdm_n_samples", 3000),
                        top_species=getattr(self.settings, "sdm_top_species", None),
                        observed=self.observed,
                        site_map=self.site,
                        precip=self.precip,
                        management=(self.management if getattr(self.settings, "use_management_in_sdm", False) else None))
                    if path:
                        self._sdm.save(path)
            except Exception:  # noqa: BLE001 - SDM은 보조이므로 실패해도 추천은 계속
                self._sdm = None
        return self._sdm

    @property
    def sdm_top3(self):
        """Top-3 candidate booster trained with planting-history features only."""
        if not getattr(self.settings, "use_top3_boost_sdm", True):
            return None
        if self._sdm_top3 is None and not self._sdm_top3_tried:
            self._sdm_top3_tried = True
            try:
                from .management_map import ManagementLayers
                from .sdm import SpeciesDistributionModel

                mgmt = self.management
                if not mgmt or not mgmt.planting:
                    return None
                planting_only = ManagementLayers(planting=mgmt.planting)
                self._sdm_top3 = SpeciesDistributionModel.train(
                    self.forest, self.terrain,
                    algos=getattr(self.settings, "sdm_algos", ("hgb",)),
                    n_samples=getattr(self.settings, "sdm_n_samples", 3000),
                    top_species=getattr(self.settings, "sdm_top_species", None),
                    observed=self.observed,
                    site_map=self.site,
                    precip=self.precip,
                    management=planting_only)
            except Exception:  # noqa: BLE001
                self._sdm_top3 = None
        return self._sdm_top3


def resolve_location(
    photo=None, lat: Optional[float] = None, lon: Optional[float] = None
) -> tuple[Optional[float], Optional[float], dict]:
    """사진 EXIF 또는 명시 좌표에서 (lat, lon, meta) 결정."""
    meta = {"source": None}
    if photo is not None:
        gps: GpsResult = extract_gps(photo)
        meta = gps.as_dict()
        if gps.ok:
            return gps.lat, gps.lon, meta
        # EXIF 실패 → 명시 좌표 폴백
    if lat is not None and lon is not None:
        meta = {"source": "manual", "lat": lat, "lon": lon}
        return float(lat), float(lon), meta
    return None, None, meta


def analyze(
    photo=None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    goal: Optional[str] = None,
    audience: str = "시민",
    top_k: int = 8,
    sources: Optional[DataSources] = None,
    gemini_api_key: Optional[str] = None,
    explain: bool = True,
    use_sdm: bool = True,
    radius_m: int = 1000,
    compute_reliability: bool = False,
) -> dict:
    """
    전체 분석 수행. 반환 구조:
      {
        ok, message,
        location: {lat, lon, source, ...},
        forest_info: {...} | None,
        site: {lat, lon, elevation_m, slope_deg, aspect_dir, climate_zone, warmth_index},
        recommendations: [ {...}, ... ],
        explanation: {text, source, model},
      }
    """
    sources = sources or DataSources()

    # 1) 위치 결정
    rlat, rlon, locmeta = resolve_location(photo, lat, lon)
    if rlat is None:
        return {"ok": False, "message": "위치를 확인할 수 없습니다. 사진에 GPS가 없으면 좌표를 직접 입력하세요.",
                "location": locmeta, "recommendations": []}

    # 2) 입지 질의
    fq = sources.forest.query(rlon, rlat, point_crs=CRS_WGS84)
    tq = sources.terrain.query(rlon, rlat, point_crs=CRS_WGS84)
    sq = sources.site.query(rlon, rlat, point_crs=CRS_WGS84) if sources.site else None
    sdq = sources.site_detail.query(rlon, rlat, point_crs=CRS_WGS84) if sources.site_detail else None
    pq = sources.precip.query(rlon, rlat, point_crs=CRS_WGS84) if sources.precip else None
    mq = sources.management.query(rlon, rlat, point_crs=CRS_WGS84) if sources.management else None
    mr = sources.management.radius_summary(rlon, rlat, point_crs=CRS_WGS84) if sources.management else None

    if not tq.found and not fq.found:
        return {"ok": False,
                "message": "해당 좌표가 임상도/DEM 데이터 범위 밖입니다. (강원권 등 데이터 보유 지역인지 확인)",
                "location": {"lat": rlat, "lon": rlon, **locmeta},
                "recommendations": []}

    # 3) 기후대
    elev = tq.elevation_m
    cz = classify_zone(rlat, elev or 0.0)

    # 4) 인접 경험적 수종
    neighborhood = sources.forest.neighborhood_species(rlon, rlat, point_crs=CRS_WGS84)

    # 5) 추천
    site = SiteContext(
        lat=rlat, lon=rlon, elevation_m=elev, slope_deg=tq.slope_deg,
        aspect_dir=tq.aspect_dir, aspect_deg=tq.aspect_deg, climate=cz,
        neighborhood=neighborhood,
        existing_forest_type=fq.attributes.get("임종") if fq.found else None,
    )
    # SDM(데이터기반 ML) 블렌딩 — 모델 신뢰도(f1)에 비례해 가중치 자동 조절.
    # 강한 모델(실데이터)은 크게, 약한 모델(데이터 부족)은 작게 반영 → 항상 안전.
    from .recommender import SDM_WEIGHT
    sdm_probs = None
    sdm_used = False
    sdm_quality = None
    sdm_report = None
    sdm_primary_report = None
    sdm_top3_report = None
    sdm_top3_boosted = False
    eff_sdm_weight = SDM_WEIGHT
    if use_sdm:
        model = sources.sdm
        if model is not None:
            prob_model = sources.sdm_top3 or model
            sdm_top3_boosted = prob_model is not model
            sdm_top3_report = prob_model.report if sdm_top3_boosted else None
            top3_management = (ManagementLayers(planting=sources.management.planting)
                               if sdm_top3_boosted and sources.management else None)
            sdm_probs = prob_model.predict_for_site(
                site, sources.db, observed=sources.observed,
                site_map=sources.site,
                precip=sources.precip,
                management=(top3_management if sdm_top3_boosted else
                            (sources.management if getattr(sources.settings, "use_management_in_sdm", False) else None)))
            sdm_used = bool(sdm_probs)
            sdm_primary_report = model.report
            sdm_report = prob_model.report
            sdm_quality = model.report.get("f1_macro")
            if sdm_quality is not None:
                # f1_macro가 0.5 이상이면 만점 가중, 그 이하면 비례 축소
                eff_sdm_weight = SDM_WEIGHT * min(1.0, max(0.0, sdm_quality) / 0.5)
    recs = recommend(site, db=sources.db, goal=goal, top_k=top_k,
                     sdm_probs=sdm_probs, sdm_weight=eff_sdm_weight)
    rec_dicts = [r.as_dict() for r in recs]

    # 6) 결과 조립
    site_dict = {
        "lat": rlat, "lon": rlon,
        "elevation_m": round(elev, 1) if elev is not None else None,
        "slope_deg": round(tq.slope_deg, 1) if tq.slope_deg is not None else None,
        "aspect_dir": tq.aspect_dir,
        "climate_zone": cz.zone,
        "warmth_index": round(cz.warmth_index_est, 0),
    }
    # 현재 숲(기존 임분) 진단 — 투명한 규칙(추천과 별개 보조 기능)
    forest_dict = fq.as_dict() if fq.found else None
    diag = diagnose_stand(forest_dict, tq.as_dict())

    result = {
        "ok": True,
        "message": "분석 완료",
        "location": {"lat": rlat, "lon": rlon, **locmeta},
        "forest_info": forest_dict,
        "site_info": sq.as_dict() if sq and sq.found else None,
        "site_nearest": (not sq.inside_polygon) if sq and sq.found else None,
        "site_detail_info": sdq.as_dict() if sdq and sdq.found else None,
        "site_detail_nearest": (not sdq.inside_polygon) if sdq and sdq.found else None,
        "precip_grid": pq,
        "management_info": mq.as_dict() if mq and mq.found else None,
        "management_radius": mr,
        "forest_nearest": (not fq.inside_polygon) if fq.found else None,
        "diagnosis": diag.as_dict() if diag else None,
        "terrain": tq.as_dict(),
        "climate": cz.as_dict(),
        "neighborhood_species": neighborhood,
        "observed_climate": (sources.observed.idw(rlat, rlon)
                             if sources.observed else None),
        "observed_climate_quality": (sources.observed.quality_report()
                                     if sources.observed else None),
        "site": site_dict,
        "recommendations": rec_dicts,
        "goal": goal,
        "sdm_used": sdm_used,
        "sdm_quality": round(sdm_quality, 3) if sdm_quality is not None else None,
        "sdm_weight_applied": round(eff_sdm_weight, 1) if sdm_used else 0,
        "sdm_top3": (sdm_report or {}).get("top3_accuracy") if sdm_used else None,
        "sdm_primary_top3": (sdm_primary_report or {}).get("top3_accuracy") if sdm_used else None,
        "sdm_top3_boosted": sdm_top3_boosted if sdm_used else False,
        "sdm_top3_f1": (sdm_top3_report or {}).get("f1_macro") if sdm_top3_boosted else None,
        "sdm_f1_weighted": (sdm_report or {}).get("f1_weighted") if sdm_used else None,
        "sdm_n_classes": (sdm_report or {}).get("n_classes") if sdm_used else None,
    }

    # 6.5) 신규 공공데이터 + 추천 신뢰도 (데스크탑/실데이터 전용; 기본 OFF → 모바일/HF 안정성 유지)
    if compute_reliability:
        afq = ffq = lsq = None
        try:
            afq = sources.afforestation.query(rlon, rlat, point_crs=CRS_WGS84) if sources.afforestation else None
        except Exception:  # noqa: BLE001
            afq = None
        try:
            ffq = sources.forest_function.query(rlon, rlat, point_crs=CRS_WGS84) if sources.forest_function else None
        except Exception:  # noqa: BLE001
            ffq = None
        try:
            lsq = sources.landslide.risk_summary(rlon, rlat, radius_m, point_crs=CRS_WGS84) if sources.landslide else None
        except Exception:  # noqa: BLE001
            lsq = None
        result["afforestation"] = afq.as_dict() if (afq and afq.found) else None
        result["forest_function"] = ffq.as_dict() if (ffq and ffq.found) else None
        result["landslide"] = lsq
        try:
            from .reliability import compute_reliability as _calc_reliability
            result["reliability"] = _calc_reliability(
                sources=sources, site=site, rec_dicts=rec_dicts,
                sdm_probs=sdm_probs, radius_m=radius_m, db=sources.db,
                official_species=(afq.all_species if (afq and afq.found) else None))
        except Exception:  # noqa: BLE001 - 보조 지표이므로 실패해도 추천은 그대로
            result["reliability"] = None

    # 7) 설명
    if explain:
        ctx = {"site": site_dict, "recommendations": rec_dicts, "forest_info": result["forest_info"]}
        result["explanation"] = generate_explanation(ctx, audience=audience, api_key=gemini_api_key)
    return result
