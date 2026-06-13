"""
llm.py — Gemini 자연어 설명 + 오프라인 폴백

개발자 요구: "제미나이 API를 연결해 추천 수종·대상지 위치 정보에 대한 LLM 기반
설명을 추가." 다만 API 키가 없거나 호출 실패해도 앱이 죽지 않도록, 구조화된
결과로부터 한국어 설명을 만드는 **결정론적 템플릿 폴백**을 항상 제공한다.

또한 타겟층(시민/산주/공무원/연구자)에 따라 어조·상세도를 달리한다.
"""
from __future__ import annotations

import os
from typing import Optional

from .config import SETTINGS

AUDIENCES = {
    "시민": "일반 시민. 전문용어를 피하고 친근하고 쉬운 말로, 3~5문장.",
    "산주": "임야 소유자. 식재·관리 실익(비용/생장/수익) 중심으로 실용적으로, 5~7문장.",
    "공무원": "산림 담당 공무원. 행정·정책 관점, 근거와 표준 용어를 갖춰 6~8문장.",
    "연구자": "산림 연구자. 입지인자·적합도 근거를 정량적·기술적으로 8~10문장.",
}


def _topic_particle(word: str) -> str:
    """한국어 주제 조사 은/는을 간단히 맞춘다."""
    if not word:
        return "은"
    last = str(word).strip()[-1]
    code = ord(last)
    if 0xAC00 <= code <= 0xD7A3:
        return "은" if (code - 0xAC00) % 28 else "는"
    return "은"


def _clean_reason(reason: str) -> str:
    text = str(reason).replace("—", "-")
    text = text.replace(" ∈ 적정 ", ", 적정 범위 ")
    text = text.replace(" < 하한 ", ", 하한보다 낮음 ")
    text = text.replace(" > 상한 ", ", 상한보다 높음 ")
    return text


def _format_number(value, suffix: str = "") -> str:
    if value is None:
        return "정보 없음"
    try:
        number = float(value)
        if number.is_integer():
            return f"{int(number)}{suffix}"
        return f"{number:.1f}{suffix}"
    except (TypeError, ValueError):
        return f"{value}{suffix}"


def _build_prompt(context: dict, audience: str) -> str:
    site = context["site"]
    recs = context["recommendations"]
    tone = AUDIENCES.get(audience, AUDIENCES["시민"])
    rec_lines = []
    for i, r in enumerate(recs[:5], 1):
        reasons = "; ".join(r["주요근거"][:3])
        rec_lines.append(f"{i}. {r['수종']}({r['학명']}) 적합점수 {r['적합점수']} — {reasons}")
    rec_text = "\n".join(rec_lines) if rec_lines else "추천 가능한 수종이 없음"

    forest = context.get("forest_info") or {}
    return f"""너는 한국 산림청 적지적수에 정통한 산림 전문가다. 아래는 한 현장 위치의
입지 분석과 식재 적합 수종 추천 결과다. 이를 바탕으로 자연어 설명을 작성하라.

[대상지 위치]
- 위도/경도: {site['lat']:.5f}, {site['lon']:.5f}
- 고도: {site.get('elevation_m')} m, 경사: {site.get('slope_deg')}°, 향: {site.get('aspect_dir')}
- 기후대: {site.get('climate_zone')} (온량지수 추정 {site.get('warmth_index')})
- 현재 임상(참고): {forest.get('임종','정보없음')} / 수종 {forest.get('수종','-')}

[식재 추천 수종 (상위)]
{rec_text}

[작성 지침]
- 독자: {tone}
- 1) 이 위치가 어떤 입지인지(기후대·고도·지형) 2) 왜 위 수종이 적합한지
  3) 식재 시 유의사항 순으로 설명.
- 과장 없이, 추천 근거에 기반해 정확하게. 데이터에 없는 수치를 지어내지 말 것.
"""


def _fallback_text(context: dict, audience: str) -> str:
    """LLM 없이 구조화 결과로 만드는 한국어 설명(항상 동작)."""
    site = context["site"]
    recs = context["recommendations"]
    forest = context.get("forest_info") or {}
    zone = site.get("climate_zone", "정보없음")
    elev = site.get("elevation_m")
    slope = site.get("slope_deg")
    aspect = site.get("aspect_dir", "평지")

    lines = []
    lines.append(
        f"이 위치(위도 {site['lat']:.4f}, 경도 {site['lon']:.4f})는 "
        f"{zone} 기후대에 속하며, 고도 약 {_format_number(elev, 'm')}"
        + (f", 경사 {slope}°, {aspect}" if slope is not None else "")
        + " 입지입니다."
    )
    if forest.get("임종"):
        lines.append(
            f"현재 이 일대 임상은 '{forest.get('임종')}'"
            + (f"(우점 수종 {forest.get('수종')})" if forest.get("수종") else "")
            + "으로 확인됩니다."
        )
    if recs:
        top = recs[0]
        names = ", ".join(r["수종"] for r in recs[:3])
        top_reasons = [_clean_reason(x) for x in top.get("주요근거", [])[:2]]
        reason_text = ", ".join(top_reasons) if top_reasons else "입지 조건과 잘 맞는다는"
        lines.append(
            f"이 입지에는 {names} 등이 적합합니다. "
            f"특히 {top['수종']}{_topic_particle(top['수종'])} {reason_text} 근거로 적합점수가 가장 높습니다."
        )
        cautions = recs[0].get("유의사항") or []
        if cautions:
            caution_text = " / ".join(_clean_reason(x) for x in cautions[:2])
            lines.append(f"식재 전에는 다음 사항을 확인하는 것이 좋습니다: {caution_text}.")
    else:
        lines.append("현재 입지 조건에 부합하는 추천 수종을 찾지 못했습니다. 입력 좌표/데이터 범위를 확인하세요.")
    lines.append("(본 설명은 입지 적합도 분석에 기반한 자동 생성 결과이며, 실제 식재 전 현장 토양·배수 조사를 권장합니다.)")
    return "\n".join(lines)


def generate_explanation(
    context: dict,
    audience: str = "시민",
    api_key: Optional[str] = None,
    settings=SETTINGS,
) -> dict:
    """
    Gemini로 설명 생성. 실패/미설정 시 폴백 텍스트.
    반환: {"text": str, "source": "gemini"|"fallback", "model": str|None}
    """
    key = api_key or os.environ.get(settings.gemini_api_key_env)
    if not key:
        return {"text": _fallback_text(context, audience), "source": "fallback", "model": None}

    try:
        from google import genai  # 지연 임포트

        client = genai.Client(api_key=key)
        prompt = _build_prompt(context, audience)
        resp = client.models.generate_content(model=settings.gemini_model, contents=prompt)
        text = (resp.text or "").strip()
        if not text:
            raise ValueError("빈 응답")
        return {"text": text, "source": "gemini", "model": settings.gemini_model}
    except Exception as e:  # noqa: BLE001
        fb = _fallback_text(context, audience)
        return {"text": fb, "source": "fallback", "model": None, "error": str(e)}
