"""
rationale.py — "왜 이 수종을 추천했는지" 추천 근거 요약 생성(UI/PDF 공용).

결과 dict(analyze 산출물)만으로 근거 문장을 구성한다. '신뢰도 낮음' 대신
'현장 확인 필요' 중심의 의사결정 지원 어조를 사용한다. 데이터가 일부 없어도
가능한 근거만 모아 안전하게 반환한다(앱 비중단).
"""
from __future__ import annotations

_MODEL_NAMES = {"rf": "RF", "hgb": "HGB", "rf_hgb": "RF+HGB 앙상블"}


def build_rationale(result: dict) -> dict:
    """result → {summary: str, bullets: list[str]}."""
    try:
        recs = result.get("recommendations") or []
        top3 = [r.get("수종") for r in recs[:3] if r.get("수종")]
        top1 = top3[0] if top3 else None
        rel = result.get("reliability") or {}
        gap = rel.get("sdm_probability_gap") or {}
        nb = rel.get("neighbor_agreement") or {}
        off = rel.get("official_afforestation") or {}
        ov = rel.get("overall_reliability") or {}
        cmp = result.get("sdm_comparison") or {}
        model = _MODEL_NAMES.get(cmp.get("chosen_key"), "SDM")
        aff = result.get("afforestation") or {}
        ls = result.get("landslide") or {}
        site = result.get("site") or {}
        oc = result.get("observed_climate") or {}

        bullets = []
        if top1:
            p1 = gap.get("top1_probability")
            head = f"SDM({model}) 1순위 추천 수종: {top1}"
            head += f" (예측확률 {p1})" if p1 is not None else ""
            head += f". Top-3 후보: {', '.join(top3)}." if top3 else "."
            bullets.append(head)
        if gap.get("gap") is not None:
            bullets.append(f"1·2위 예측확률 차이 {gap.get('gap')} → 모델 확신도 {gap.get('level', '-')}.")
        if nb.get("level") and nb.get("level") != "분석 제한" and nb.get("message"):
            bullets.append("주변 실제 임분: " + str(nb.get("message")))
        if off.get("level") and off.get("level") != "분석 제한" and off.get("message"):
            bullets.append("공식 조림지도: " + str(off.get("message")))
        factors = []
        if site.get("elevation_m") is not None:
            factors.append(f"고도 {site['elevation_m']}m")
        if site.get("slope_deg") is not None:
            factors.append(f"경사 {site['slope_deg']}°")
        if site.get("aspect_dir"):
            factors.append(f"향 {site['aspect_dir']}")
        if site.get("climate_zone"):
            factors.append(f"기후대 {site['climate_zone']}")
        if oc.get("temp_c") is not None:
            try:
                factors.append(f"실측기온 {float(oc['temp_c']):.1f}℃")
            except (TypeError, ValueError):
                pass
        if factors:
            bullets.append("추천에 영향을 준 주요 입지 조건: " + ", ".join(factors) + ".")
        if ls and ls.get("point_grade") is not None:
            hr = (ls.get("high_risk_ratio") or 0) * 100
            bullets.append(f"산사태 위험등급 {ls['point_grade']}등급, 반경 내 고위험(1·2등급) 비율 {hr:.0f}%.")
        if ov.get("level") in ("낮음", "보통"):
            bullets.append("현장 확인 권장: " + str(ov.get("message")
                           or "추천 근거 간 차이가 있어 현장 토양·수분 조건 확인이 필요합니다."))

        return {"summary": _summary(top1, off, aff), "bullets": bullets}
    except Exception:  # noqa: BLE001 - 근거 요약 실패해도 결과는 표시
        return {"summary": "", "bullets": []}


def _summary(top1, off: dict, aff: dict) -> str:
    rep = ", ".join((aff.get("대표수종") or [])) if aff else ""
    lvl = (off or {}).get("level")
    if lvl == "높음":
        return ("SDM 추천 수종과 산림청 맞춤형조림지도 추천 수종이 일치하여 추천 근거가 강화됩니다. "
                "또한 주변 반경 내 유사 임분 비율이 높아 해당 수종 추천의 현장 일관성이 비교적 높습니다.")
    if lvl == "낮음" and top1:
        base = f"SDM 기반 1순위 추천 수종은 {top1}입니다."
        if rep:
            base += f" 다만 산림청 맞춤형조림지도에서는 {rep}가 대표수종으로 제시되어 SDM 추천과 일부 차이를 보입니다."
        return base + " 따라서 현장 토양, 수분, 배수 조건을 확인한 뒤 최종 수종을 결정하는 것이 적절합니다."
    if top1:
        return (f"SDM 기반 1순위 추천 수종은 {top1}입니다. 입지·주변 임분·공식 데이터를 종합한 결과이며, "
                "현장 조건을 함께 확인하면 추천 신뢰도가 높아집니다.")
    return "추천 결과를 산출할 입지 정보가 부족합니다. 좌표 또는 데이터 범위를 확인해주세요."
