"""
sdm.py — 수종분포모델(Species Distribution Model)

원본 노트북의 ML은 "사람이 만든 규칙 라벨"을 같은 피처로 재학습하는 순환학습이라
무의미했다. **올바른 ML**은 라벨을 *실제 관측치*에서 가져와야 한다. 임상도의
KOFTR_NM(그 자리에 실제로 우점하는 수종)은 훌륭한 실관측 라벨이다.

이 모듈은 임상도 임분(실제 분포) + 환경변수(고도/경사/향/위도/경도)로 다음을 학습한다:

    P(수종 | 환경)  =  HistGradientBoostingClassifier

즉 "이런 환경에서는 어떤 수종이 실제로 자라고 있는가"를 데이터로 학습한다(누수 없음).
이는 생태학의 **종분포모델(SDM)** 과 정확히 같은 접근이며, RandomForest/XGBoost를
'쓰려면 이렇게 써야 하는' 정석이다. 추천 엔진은 이 확률을 *데이터기반 2차 의견*으로
지식기반 적지적수 점수와 블렌딩한다(recommender.recommend(sdm_probs=...)).

요구: scikit-learn. (HistGradientBoosting은 XGBoost/LightGBM급 성능에 추가 의존성 없음)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from .config import CRS_WGS84, CRS_KOREA_TM
from .management_map import MANAGEMENT_FEATURES

FEATURES = ["elevation", "slope", "aspect_sin", "aspect_cos", "lat", "lon"]
SITE_FEATURES = [
    "site_alt", "site_slope", "site_aspect",
    "rock_large", "rock_mid", "climate_code", "terrain_group",
    "deposit_form", "slope_type", "soil_depth", "soil_texture", "soil_type",
]
PRECIP_FEATURES = [
    "wc_annual_precip", "wc_growing_precip",
    "wc_summer_precip", "wc_winter_precip",
]
SITE_DETAIL_FEATURES = [
    "detail_soil_type", "detail_soil_quality", "detail_relief",
    "detail_weathering", "detail_terrain_group", "detail_climate_code",
    "detail_rock_large", "detail_soil_drainage", "detail_slope",
    "detail_altitude_code", "detail_deposit", "detail_erosion",
    "detail_slope_type", "detail_aspect_code", "detail_rock_exposure",
    "detail_ridge_valley", "detail_wind_exposure", "detail_water_effect",
    "detail_valid_soil_depth", "detail_a_depth", "detail_b_depth",
    "detail_a_texture", "detail_b_texture", "detail_a_structure",
    "detail_b_structure",
]

# 비수종(비산림) 임상도 라벨 — SDM 학습에서 제외(수종이 아님: 벌채지/무립목지/수면 등).
# 이런 라벨을 한 클래스로 학습하면 환경변수로 '맨땅'을 예측하려다 f1이 깎인다.
_NONFOREST_LABELS = {
    "제지", "미립목지", "무립목지", "미입목지", "제지지", "벌채지",
    "수면", "경작지", "초지", "기타", "비산림",
}
# 그룹/혼효 라벨 — 특정 수종이 아니라 잡종 카테고리라 모든 환경에 걸쳐 나타나
# 분류기를 혼란시키고(누구의 적지도 아님) 추천에서 단일 수종으로 매핑되지도 않는다.
# SDM 학습에서 빼면 f1·top-3가 크게 오르며, 경험적 인접빈도 경로는 그대로 활용된다.
_GROUP_LABELS = {"기타활엽수", "기타참나무류", "기타침엽수", "침활혼효림"}

# SDM 학습 기본 제외 라벨(비수종 + 그룹라벨).
_DEFAULT_SDM_EXCLUDE = _NONFOREST_LABELS | _GROUP_LABELS


def _num(v) -> float:
    """None/결측을 NaN으로(HGB는 NaN을 native 처리)."""
    try:
        return float(v) if v is not None else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _aspect_components(aspect_deg: Optional[float]) -> tuple[float, float]:
    """향(0~360)을 순환 인코딩(sin, cos). 평지/결측은 (0,0)."""
    if aspect_deg is None or (isinstance(aspect_deg, float) and math.isnan(aspect_deg)):
        return 0.0, 0.0
    r = math.radians(aspect_deg)
    return math.sin(r), math.cos(r)


def _code(v) -> float:
    """Categorical code as numeric feature; missing/unknown becomes -1."""
    try:
        if v is None:
            return -1.0
        s = str(v).strip()
        return float(s) if s else -1.0
    except (TypeError, ValueError):
        return -1.0


def _site_feature_row(site_raw: Optional[dict]) -> list[float]:
    """산림입지도 raw dict → SDM feature row."""
    site_raw = site_raw or {}
    return [
        _num(site_raw.get("LOCTN_ALTT")),
        _num(site_raw.get("LOCTN_GRDN")),
        _num(site_raw.get("EIGHT_AGL")),
        _code(site_raw.get("PRRCK_LARG")),
        _code(site_raw.get("PRRCK_MDDL")),
        _code(site_raw.get("CLZN_CD")),
        _code(site_raw.get("TPGRP_TPCD")),
        _code(site_raw.get("PRDN_FOM_C")),
        _code(site_raw.get("SLANT_TYP")),
        _code(site_raw.get("SLDPT_TPCD")),
        _code(site_raw.get("SCSTX_CD")),
        _code(site_raw.get("SLTP_CD")),
    ]


def _precip_feature_row(precip: Optional[dict]) -> list[float]:
    precip = precip or {}
    return [
        _num(precip.get("annual_mean_mm")),
        _num(precip.get("growing_may_sep_mm")),
        _num(precip.get("summer_jun_aug_mm")),
        _num(precip.get("winter_dec_feb_mm")),
    ]


def _detail_feature_row(detail_raw: Optional[dict]) -> list[float]:
    detail_raw = detail_raw or {}
    return [
        _code(detail_raw.get("SLTP_CD")),
        _code(detail_raw.get("STQLT_CD")),
        _code(detail_raw.get("RHGLT_GGRP")),
        _code(detail_raw.get("WTHR_CD")),
        _code(detail_raw.get("TPGRP_TPCD")),
        _code(detail_raw.get("CLZN_CD")),
        _code(detail_raw.get("PRRCK_LARG")),
        _code(detail_raw.get("SOIL_DRNGE")),
        _num(detail_raw.get("LOCTN_GRDN")),
        _code(detail_raw.get("ALTTD_CD")),
        _code(detail_raw.get("ACCMA_FOR")),
        _code(detail_raw.get("WASH_CD")),
        _code(detail_raw.get("SLANT_TYP")),
        _code(detail_raw.get("EIGHT_CD")),
        _code(detail_raw.get("ROCK_EXDGR")),
        _code(detail_raw.get("RIDGE_VS")),
        _code(detail_raw.get("WIND_EXDGR")),
        _code(detail_raw.get("WTEFF_DGR")),
        _num(detail_raw.get("VLDTY_SLDP")),
        _num(detail_raw.get("SIAFLR_SLD")),
        _num(detail_raw.get("SIBFLR_SLD")),
        _code(detail_raw.get("SIAFLR_SCS")),
        _code(detail_raw.get("SIBFLR_SCS")),
        _code(detail_raw.get("SIAFLR_STR")),
        _code(detail_raw.get("SIBFLR_STR")),
    ]


@dataclass
class SDMResult:
    probs: dict[str, float]       # KOFTR 라벨 → 확률
    top: list[tuple[str, float]]  # 상위 (수종, 확률)


_ALGOS = ("hgb", "rf")  # 지원 알고리즘: HistGradientBoosting / RandomForest


def _make_estimator(name: str, random_state: int):
    if name == "hgb":
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.08, max_depth=None,
            l2_regularization=1.0, random_state=random_state)
    if name == "rf":
        from sklearn.ensemble import RandomForestClassifier
        return RandomForestClassifier(
            n_estimators=500, max_features="sqrt", n_jobs=-1, class_weight="balanced",
            random_state=random_state)
    raise ValueError(f"알 수 없는 알고리즘 '{name}' (지원: {_ALGOS})")


class SpeciesDistributionModel:
    """
    임상도 실관측 기반 종분포모델.

    estimators: [(이름, 학습된 분류기)] 리스트. 1개면 단일 모델(기본 HGB),
    2개 이상이면 **앙상블**(예측 확률 평균). 모든 분류기는 같은 라벨로 학습되어
    classes_ 순서가 동일하므로 열 단위 평균이 정합한다.
    """

    def __init__(self, estimators, classes: list[str], n_train: int, report: dict,
                 feature_names: Optional[list] = None):
        self.estimators = estimators
        self.classes = list(classes)
        self.n_train = n_train
        self.report = report
        # 이 모델이 학습한 피처 순서(기본=지형 5피처). 측정기후 사용 시 temp_obs/precip_obs 추가.
        self.feature_names = list(feature_names) if feature_names else list(FEATURES)

    @property
    def uses_climate(self) -> bool:
        return "temp_obs" in self.feature_names

    @property
    def algos(self) -> list[str]:
        return [name for name, _ in self.estimators]

    def _proba(self, X):
        """앙상블 평균 확률(단일 모델이면 그 모델 확률 그대로)."""
        return np.mean([clf.predict_proba(X) for _, clf in self.estimators], axis=0)

    # ---- 평가 지표 ----
    @staticmethod
    def _metrics_from_proba(proba, yte, classes) -> dict:
        """확률행렬(앙상블 평균 또는 단일)로 accuracy/f1/top3 산출."""
        from sklearn.metrics import accuracy_score, f1_score
        classes = list(classes)
        pred = np.array(classes)[np.argmax(proba, axis=1)]
        top3 = None
        try:
            from sklearn.metrics import top_k_accuracy_score
            k = min(3, len(classes) - 1)
            if k >= 1:
                top3 = round(float(top_k_accuracy_score(yte, proba, k=k, labels=classes)), 3)
        except Exception:  # noqa: BLE001
            top3 = None
        return {
            "accuracy": round(float(accuracy_score(yte, pred)), 3),
            "f1_macro": round(float(f1_score(yte, pred, average="macro")), 3),
            "f1_weighted": round(float(f1_score(yte, pred, average="weighted")), 3),
            "top3_accuracy": top3,
        }

    # ---- 피처행렬 생성(학습/비교가 공유) ----
    @classmethod
    def _build_xy(cls, forest_map, terrain, n_samples, min_class, random_state,
                  exclude_labels, top_species, observed, site_map, precip,
                  site_detail_map, management):
        """임상도 표본 → (X, y, feat_names). 무거운 피처 질의를 1회만 수행."""
        import geopandas as gpd

        gdf = forest_map.gdf
        if "KOFTR_NM" not in gdf.columns:
            raise ValueError("임상도에 KOFTR_NM 컬럼이 없어 SDM을 학습할 수 없습니다.")

        # 비수종·그룹 라벨 제외 후, (선택) 가장 흔한 상위 N종만 학습 — 롱테일 완화로 f1↑.
        exclude = _DEFAULT_SDM_EXCLUDE if exclude_labels is None else set(exclude_labels)
        work = gdf[["geometry", "KOFTR_NM"]].copy()
        work["KOFTR_NM"] = work["KOFTR_NM"].astype(str)
        work = work[~work["KOFTR_NM"].isin(exclude)]
        if top_species:
            top = work["KOFTR_NM"].value_counts().head(top_species).index
            work = work[work["KOFTR_NM"].isin(top)]
        if work.empty:
            raise ValueError("제외/상위N 필터 후 학습할 임분이 없습니다.")

        n = min(n_samples, len(work))
        sample = work.sample(n=n, random_state=random_state)

        # 폴리곤 내부가 보장되는 대표점(도넛형 대비) → 4326으로 변환
        rep = sample.geometry.representative_point()
        rep_wgs = gpd.GeoSeries(rep, crs=work.crs).to_crs(CRS_WGS84)

        # 측정기후(기온/강수)를 피처로 쓸지 — 관측소 데이터(ObservedClimate)가 있으면 추가.
        # 실측 기후는 종분포를 가르는 1차 요인이라 f1을 유의하게 올린다(좌표가 거칠어도 유효).
        feat_names = list(FEATURES)
        if observed:
            feat_names += ["temp_obs", "precip_obs"]
        if site_map:
            feat_names += list(SITE_FEATURES)
        if precip:
            feat_names += list(PRECIP_FEATURES)
        if site_detail_map:
            feat_names += list(SITE_DETAIL_FEATURES)
        if management:
            feat_names += list(MANAGEMENT_FEATURES)
        rows, labels = [], []
        for geom, koftr in zip(rep_wgs.values, sample["KOFTR_NM"].values):
            tq = terrain.query(geom.x, geom.y, point_crs=CRS_WGS84)
            if not tq.found or tq.elevation_m is None:
                continue
            asin, acos = _aspect_components(tq.aspect_deg)
            row = [
                tq.elevation_m,
                tq.slope_deg if tq.slope_deg is not None else 0.0,
                asin, acos, geom.y, geom.x,
            ]
            if observed:
                # IDW 보간(주변 관측소 거리가중 평균) — 강원 전역에 매끄럽게 값 부여.
                oc = observed.idw(geom.y, geom.x) or {}
                row += [_num(oc.get("temp_c")), _num(oc.get("precip_mm"))]
            if site_map:
                sq = site_map.query(geom.x, geom.y, point_crs=CRS_WGS84)
                row += _site_feature_row(sq.raw if sq and sq.found else None)
            if precip:
                row += _precip_feature_row(precip.query(geom.x, geom.y, point_crs=CRS_WGS84))
            if site_detail_map:
                sdq = site_detail_map.query(geom.x, geom.y, point_crs=CRS_WGS84)
                row += _detail_feature_row(sdq.raw if sdq and sdq.found else None)
            if management:
                mq = management.query(geom.x, geom.y, point_crs=CRS_WGS84)
                row += mq.feature_row() if mq else [0.0] * len(MANAGEMENT_FEATURES)
            rows.append(row)
            labels.append(str(koftr))

        X = np.array(rows, dtype="float64")
        y = np.array(labels)
        if len(X) < 50:
            raise ValueError(f"학습 표본 부족({len(X)}). 데이터 범위/품질을 확인하세요.")

        # 표본이 너무 적은 희귀 클래스 제거(노이즈 방지)
        uniq, counts = np.unique(y, return_counts=True)
        keep = set(uniq[counts >= min_class])
        mask = np.array([lbl in keep for lbl in y])
        X, y = X[mask], y[mask]
        if len(set(y)) < 2:
            raise ValueError("유효 수종 클래스가 2개 미만입니다.")
        return X, y, feat_names

    # ---- 학습(단일 또는 앙상블) ----
    @classmethod
    def train(cls, forest_map, terrain, n_samples: int = 3000, min_class: int = 15,
              random_state: int = 42, test_size: float = 0.2, algos: tuple = ("hgb",),
              exclude_labels: Optional[set] = None, top_species: Optional[int] = None,
              use_sample_weight: bool = True, observed=None, site_map=None, precip=None,
              site_detail_map=None, management=None) -> "SpeciesDistributionModel":
        from sklearn.model_selection import train_test_split
        X, y, feat_names = cls._build_xy(forest_map, terrain, n_samples, min_class,
                                         random_state, exclude_labels, top_species,
                                         observed, site_map, precip, site_detail_map, management)
        Xtr, Xte, ytr, yte = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=y)
        sw = None
        if use_sample_weight:
            from sklearn.utils.class_weight import compute_sample_weight
            sw = compute_sample_weight("balanced", ytr)
        estimators = []
        for name in algos:
            clf = _make_estimator(name, random_state)
            if name == "hgb" and sw is not None:
                clf.fit(Xtr, ytr, sample_weight=sw)
            else:
                clf.fit(Xtr, ytr)   # rf는 class_weight='balanced' 내장
            estimators.append((name, clf))
        ref = estimators[0][1]
        proba = np.mean([clf.predict_proba(Xte) for _, clf in estimators], axis=0)
        report = {
            "n_total": int(len(X)), "n_classes": int(len(set(y))), "algos": list(algos),
            **cls._metrics_from_proba(proba, yte, ref.classes_),
            "classes": sorted(str(c) for c in set(y)), "features": feat_names,
        }
        return cls(estimators, [str(c) for c in ref.classes_], n_train=len(Xtr),
                   report=report, feature_names=feat_names)

    # ---- 3개 모델 비교(RF / HGB / RF+HGB) — 피처는 1회만 생성 ----
    @classmethod
    def train_comparison(cls, forest_map, terrain, n_samples: int = 8000, min_class: int = 15,
                         random_state: int = 42, test_size: float = 0.2, top_species: int = 5,
                         observed=None, site_map=None, precip=None, management=None) -> dict:
        from sklearn.model_selection import train_test_split
        from sklearn.utils.class_weight import compute_sample_weight
        X, y, feat_names = cls._build_xy(forest_map, terrain, n_samples, min_class,
                                         random_state, None, top_species,
                                         observed, site_map, precip, None, management)
        Xtr, Xte, ytr, yte = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=y)
        sw = compute_sample_weight("balanced", ytr)
        meta = {"n_total": int(len(X)), "n_classes": int(len(set(y))),
                "classes": sorted(str(c) for c in set(y)), "features": feat_names}

        rf = _make_estimator("rf", random_state)
        rf.fit(Xtr, ytr)
        rf_classes = [str(c) for c in rf.classes_]
        rf_report = {"algos": ["rf"], "n_train": int(len(Xtr)),
                     **cls._metrics_from_proba(rf.predict_proba(Xte), yte, rf.classes_), **meta}
        reports = {"rf": rf_report}
        models = {"rf": cls([("rf", rf)], rf_classes, len(Xtr), rf_report, feat_names)}

        hgb_ok = False
        try:
            hgb = _make_estimator("hgb", random_state)
            hgb.fit(Xtr, ytr, sample_weight=sw)
            hgb_report = {"algos": ["hgb"], "n_train": int(len(Xtr)),
                          **cls._metrics_from_proba(hgb.predict_proba(Xte), yte, hgb.classes_), **meta}
            ens_proba = np.mean([rf.predict_proba(Xte), hgb.predict_proba(Xte)], axis=0)
            ens_report = {"algos": ["rf", "hgb"], "n_train": int(len(Xtr)),
                          **cls._metrics_from_proba(ens_proba, yte, rf.classes_), **meta}
            reports["hgb"] = hgb_report
            reports["rf_hgb"] = ens_report
            models["hgb"] = cls([("hgb", hgb)], [str(c) for c in hgb.classes_], len(Xtr), hgb_report, feat_names)
            models["rf_hgb"] = cls([("rf", rf), ("hgb", hgb)], rf_classes, len(Xtr), ens_report, feat_names)
            hgb_ok = True
        except Exception:  # noqa: BLE001 - HGB 실패 시 RF 단독으로 폴백
            hgb_ok = False
        chosen_key = "rf_hgb" if hgb_ok else "rf"
        return {"reports": reports, "models": models, "chosen": models[chosen_key],
                "chosen_key": chosen_key, "hgb_ok": hgb_ok, "feature_names": feat_names}

    # ---- 예측 ----
    def predict(self, elevation, slope, aspect_deg, lat, lon=None,
                temp_obs=None, precip_obs=None, site_raw=None,
                precip_raw=None, site_detail_raw=None, management_raw=None) -> SDMResult:
        asin, acos = _aspect_components(aspect_deg)
        # 예전 호출부 호환용: lon이 생략되면 강원권 중앙 경도값을 사용한다.
        # 앱/pipeline에서는 실제 GPS 경도를 항상 전달한다.
        if lon is None:
            lon = 128.0
        row = [elevation, slope if slope is not None else 0.0, asin, acos, lat, lon]
        if self.uses_climate:   # 학습 때 기후피처를 썼다면 예측도 동일 구성으로
            row += [_num(temp_obs), _num(precip_obs)]
        if any(f in self.feature_names for f in SITE_FEATURES):
            row += _site_feature_row(site_raw)
        if any(f in self.feature_names for f in PRECIP_FEATURES):
            row += _precip_feature_row(precip_raw)
        if any(f in self.feature_names for f in SITE_DETAIL_FEATURES):
            row += _detail_feature_row(site_detail_raw)
        if any(f in self.feature_names for f in MANAGEMENT_FEATURES):
            if management_raw is not None:
                row += management_raw.feature_row()
            else:
                row += [0.0] * len(MANAGEMENT_FEATURES)
        x = np.array([row], dtype="float64")
        proba = self._proba(x)[0]
        probs = {c: float(p) for c, p in zip(self.classes, proba)}
        top = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
        return SDMResult(probs=probs, top=top)

    def predict_for_site(self, site, db, observed=None, site_map=None,
                         precip=None, site_detail_map=None, management=None) -> dict[str, float]:
        """site 환경에서 예측한 확률을 KB 수종명으로 매핑해 반환."""
        if site.elevation_m is None:
            return {}
        temp_obs = precip_obs = None
        if self.uses_climate and observed is not None:
            oc = observed.idw(site.lat, site.lon) or {}
            temp_obs, precip_obs = oc.get("temp_c"), oc.get("precip_mm")
        site_raw = None
        if any(f in self.feature_names for f in SITE_FEATURES) and site_map is not None:
            sq = site_map.query(site.lon, site.lat, point_crs=CRS_WGS84)
            site_raw = sq.raw if sq and sq.found else None
        precip_raw = None
        if any(f in self.feature_names for f in PRECIP_FEATURES) and precip is not None:
            precip_raw = precip.query(site.lon, site.lat, point_crs=CRS_WGS84)
        site_detail_raw = None
        if any(f in self.feature_names for f in SITE_DETAIL_FEATURES) and site_detail_map is not None:
            sdq = site_detail_map.query(site.lon, site.lat, point_crs=CRS_WGS84)
            site_detail_raw = sdq.raw if sdq and sdq.found else None
        management_raw = None
        if any(f in self.feature_names for f in MANAGEMENT_FEATURES) and management is not None:
            management_raw = management.query(site.lon, site.lat, point_crs=CRS_WGS84)
        res = self.predict(site.elevation_m, site.slope_deg,
                           getattr(site, "aspect_deg", None), site.lat, site.lon,
                           temp_obs=temp_obs, precip_obs=precip_obs,
                           site_raw=site_raw, precip_raw=precip_raw,
                           site_detail_raw=site_detail_raw,
                           management_raw=management_raw)
        out: dict[str, float] = {}
        for koftr, p in res.probs.items():
            sp = db.match(koftr)
            if sp:
                out[sp.korean_name] = out.get(sp.korean_name, 0.0) + p
        return out

    # ---- 영속화 ----
    def save(self, path: str | Path):
        import joblib
        joblib.dump({"estimators": self.estimators, "classes": self.classes,
                     "n_train": self.n_train, "report": self.report,
                     "feature_names": self.feature_names}, path)

    @classmethod
    def load(cls, path: str | Path) -> "SpeciesDistributionModel":
        import joblib
        d = joblib.load(path)
        return cls(d["estimators"], d["classes"], d["n_train"], d["report"],
                   feature_names=d.get("feature_names"))


# 모델별 캐시 파일명(요청 사양)
_CMP_FILES = {"rf": "sdm_rf.joblib", "hgb": "sdm_hgb.joblib",
              "rf_hgb": "sdm_rf_hgb_ensemble.joblib"}


def load_or_train_comparison(forest_map, terrain, *, settings, n_samples, top_species,
                             observed=None, site_map=None, precip=None, management=None) -> dict:
    """RF/HGB/RF+HGB 비교를 디스크 캐시와 함께 반환. 동일 데이터·옵션이면 재학습하지 않는다.

    모델별 joblib(sdm_rf / sdm_hgb / sdm_rf_hgb_ensemble)와 메타(reports·signature)를
    data_dir/models 에 저장한다. (in-session 캐시는 호출부의 st.cache_resource가 담당)
    """
    import json
    models_dir = Path(settings.data_dir) / "models"
    flags = "".join(k for k, v in (("o", observed), ("s", site_map),
                                   ("p", precip), ("m", management)) if v)
    signature = f"n{n_samples}_t{top_species}_{flags}"
    meta_path = models_dir / "sdm_comparison_meta.json"
    paths = {k: models_dir / v for k, v in _CMP_FILES.items()}

    try:
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("signature") == signature and paths["rf"].exists():
                models = {"rf": SpeciesDistributionModel.load(paths["rf"])}
                hgb_ok = bool(meta.get("hgb_ok"))
                if hgb_ok and paths["hgb"].exists() and paths["rf_hgb"].exists():
                    models["hgb"] = SpeciesDistributionModel.load(paths["hgb"])
                    models["rf_hgb"] = SpeciesDistributionModel.load(paths["rf_hgb"])
                else:
                    hgb_ok = False
                chosen_key = meta.get("chosen_key", "rf")
                if chosen_key not in models:
                    chosen_key = "rf"
                return {"reports": meta["reports"], "models": models,
                        "chosen": models[chosen_key], "chosen_key": chosen_key,
                        "hgb_ok": hgb_ok, "feature_names": meta.get("feature_names"),
                        "cached": True}
    except Exception:  # noqa: BLE001 - 캐시 손상 시 재학습
        pass

    comp = SpeciesDistributionModel.train_comparison(
        forest_map, terrain, n_samples=n_samples, top_species=top_species,
        observed=observed, site_map=site_map, precip=precip, management=management)
    try:
        models_dir.mkdir(parents=True, exist_ok=True)
        for k, m in comp["models"].items():
            m.save(paths[k])
        meta_path.write_text(json.dumps({
            "signature": signature, "reports": comp["reports"],
            "chosen_key": comp["chosen_key"], "hgb_ok": comp["hgb_ok"],
            "feature_names": comp["feature_names"]}, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001 - 저장 실패해도 메모리 결과는 사용
        pass
    comp["cached"] = False
    return comp
