"""HTML and PDF report builders for Forest AI analysis results."""
from __future__ import annotations

from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path


NO_INFO = "정보 없음"


def _plain(value, suffix: str = "") -> str:
    if value is None:
        return NO_INFO
    try:
        if value != value:  # NaN
            return NO_INFO
    except Exception:
        pass
    text = str(value).strip()
    if not text:
        return NO_INFO
    return text + suffix


def _html_value(value, suffix: str = "") -> str:
    return escape(_plain(value, suffix))


def _row(label: str, value, suffix: str = "") -> str:
    return f"<tr><th>{escape(label)}</th><td>{_html_value(value, suffix)}</td></tr>"


def _radius_lines(data: dict, main_key: str = "") -> list[str]:
    lines = []
    for radius in ("500", "1000", "3000"):
        item = data.get(radius, {}) or {}
        label = "1km" if radius == "1000" else f"{radius}m"
        bits = [f"{label}: {item.get('count', 0)}건"]
        if item.get(main_key):
            bits.append(f"주요 항목 {item.get(main_key)}")
        if item.get("latest_year"):
            bits.append(f"최근 {item.get('latest_year')}년")
        if item.get("nearest_m") is not None:
            bits.append(f"최근접 {item.get('nearest_m')}m")
        lines.append(" · ".join(bits))
    return lines


def _radius_rows(title: str, data: dict, main_key: str = "") -> str:
    if not data:
        return f"<p>{escape(title)}: {NO_INFO}</p>"
    rows = "".join(f"<li>{escape(line)}</li>" for line in _radius_lines(data, main_key))
    return f"<h3>{escape(title)}</h3><ul>{rows}</ul>"


def _reliability_html(rel: dict) -> str:
    """추천 신뢰도 분석 섹션(데스크탑 분석 시에만 result에 존재)."""
    if not rel:
        return ""
    ov = rel.get("overall_reliability") or {}
    gap = rel.get("sdm_probability_gap") or {}
    nb = rel.get("neighbor_agreement") or {}
    dv = rel.get("environment_diversity") or {}
    radius = rel.get("radius_m")
    rlabel = "1km" if radius == 1000 else (f"{radius}m" if radius else "")
    _head = {"높음": "추천 근거가 안정적인 구간", "보통": "현장 확인 권장 구간",
             "낮음": "현장 확인 필요 구간", "분석 제한": "신뢰도 정보 제한"}.get(ov.get("level"), "신뢰도 분석")
    return f"""
  <h2>8. 추천 신뢰도 분석</h2>
  <p class="note"><b>{escape(_head)}</b><br>{_html_value(ov.get('message'))}</p>
  <table>
    {_row("SDM 확률 차이 신뢰도", gap.get('level'))}
    {_row(f"주변 임분 일치도(반경 {rlabel})", nb.get('level'))}
    {_row(f"환경 다양성 지수(반경 {rlabel})", dv.get('level'))}
  </table>
  <ul>
    <li>{_html_value(gap.get('message'))}</li>
    <li>{_html_value(nb.get('message'))}</li>
    <li>{_html_value(dv.get('message'))}</li>
  </ul>
"""


def _official_html(d: dict) -> str:
    """공식 데이터(맞춤형조림지도·산림기능구분도·산사태위험지도) 비교 섹션."""
    aff = d.get("afforestation") or {}
    ff = d.get("forest_function") or {}
    ls = d.get("landslide") or {}
    off = (d.get("reliability") or {}).get("official_afforestation") or {}
    if not (aff or ff or ls):
        return ""
    rows = ""
    if aff:
        rows += _row("공식 대표수종(맞춤형조림지도)", ", ".join(aff.get("대표수종") or []) or NO_INFO)
        if aff.get("추가수종"):
            rows += _row("추가 수종", ", ".join(aff.get("추가수종")))
        if off.get("message"):
            rows += _row("공식 조림 일치", f"{off.get('level', '')} — {off.get('message', '')}")
    if ff:
        rows += _row("공식 산림기능", (ff.get("주기능") or NO_INFO)
                     + (" (절대보전지역)" if ff.get("절대보전지역") else ""))
    if ls:
        rows += _row("산사태 위험등급(지점)", f"{ls.get('point_grade')}등급 {ls.get('point_label', '')}")
        rows += _row("반경 고위험(1·2등급) 비율", f"{(ls.get('high_risk_ratio') or 0) * 100:.0f}%")
    return f"<h2>9. 공식 데이터 비교 · 재해</h2><table>{rows}</table>"


def _collect_report_data(result: dict) -> dict:
    return {
        "loc": result.get("location") or {},
        "site": result.get("site") or {},
        "forest": result.get("forest_info") or {},
        "site_info": result.get("site_info") or {},
        "detail": result.get("site_detail_info") or {},
        "observed": result.get("observed_climate") or {},
        "precip": result.get("precip_grid") or {},
        "diag": result.get("diagnosis") or {},
        "mg_radius": result.get("management_radius") or {},
        "reliability": result.get("reliability") or {},
        "afforestation": result.get("afforestation") or {},
        "forest_function": result.get("forest_function") or {},
        "landslide": result.get("landslide") or {},
        "recs": result.get("recommendations") or [],
        "explanation": (result.get("explanation") or {}).get("text"),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def create_report(result: dict) -> str:
    """Create a self-contained HTML report from analyze() result."""
    d = _collect_report_data(result)
    loc = d["loc"]
    site = d["site"]
    forest = d["forest"]
    site_info = d["site_info"]
    detail = d["detail"]
    observed = d["observed"]
    precip = d["precip"]
    diag = d["diag"]
    mg_radius = d["mg_radius"]

    rec_cards = []
    for i, rec in enumerate(d["recs"][:3], 1):
        reasons = "".join(f"<li>{escape(str(x))}</li>" for x in rec.get("주요근거", [])[:5])
        cautions = rec.get("유의사항") or ["뚜렷한 감점 요인은 확인하지 않았습니다."]
        caution_html = "".join(f"<li>{escape(str(x))}</li>" for x in cautions[:5])
        rec_cards.append(f"""
        <section class="card">
          <h3>{i}. {_html_value(rec.get('수종'))}</h3>
          <p><b>학명</b> {_html_value(rec.get('학명'))}</p>
          <p><b>최종점수</b> {_html_value(rec.get('적합점수'))} · <b>탄소흡수</b> {_html_value(rec.get('탄소흡수'))} · <b>유형</b> {_html_value(rec.get('유형'))}</p>
          <h4>추천 근거</h4><ul>{reasons or '<li>정보 없음</li>'}</ul>
          <h4>위험/주의 요인</h4><ul>{caution_html}</ul>
        </section>
        """)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>Forest AI 분석 보고서</title>
  <style>
    body {{font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:#172017; margin:32px; line-height:1.55;}}
    h1 {{color:#1b5e20;}}
    h2 {{border-bottom:2px solid #dce8dc; padding-bottom:6px; margin-top:30px;}}
    table {{border-collapse:collapse; width:100%; margin:10px 0 18px;}}
    th, td {{border:1px solid #d9e2d9; padding:8px 10px; text-align:left; vertical-align:top;}}
    th {{width:32%; background:#f1f8e9;}}
    .card {{border:1px solid #d9e2d9; border-radius:8px; padding:14px 16px; margin:12px 0;}}
    .note {{background:#f7faf7; border-left:4px solid #2e7d32; padding:10px 12px;}}
  </style>
</head>
<body>
  <h1>Forest AI 분석 보고서</h1>
  <p class="note">강원권 산림 입지 환경을 분석해 Top-3 수종 후보와 추천 근거를 정리한 의사결정 지원 보고서입니다.</p>

  <h2>1. 분석 위치</h2>
  <table>
    {_row("위도", loc.get("lat"))}
    {_row("경도", loc.get("lon"))}
    {_row("분석일자", d["generated"])}
  </table>

  <h2>2. 현재 숲 정보</h2>
  <table>
    {_row("임상", forest.get("임종"))}
    {_row("주요 수종", forest.get("수종"))}
    {_row("영급", forest.get("영급"))}
    {_row("경급", forest.get("경급"))}
    {_row("밀도", forest.get("밀도"))}
  </table>

  <h2>3. 입지 환경 분석</h2>
  <table>
    {_row("고도", site.get("elevation_m"), "m")}
    {_row("경사", site.get("slope_deg"), "°")}
    {_row("사면방향", site.get("aspect_dir"))}
    {_row("기후대", site.get("climate_zone"))}
    {_row("토양형", site_info.get("토양형코드") or detail.get("토양형코드"))}
    {_row("토심", site_info.get("토심코드") or detail.get("유효토심"))}
    {_row("배수", detail.get("토양배수코드"))}
    {_row("평균기온", observed.get("temp_c"), "℃")}
    {_row("강수량", observed.get("precip_mm"), "mm")}
    {_row("격자 연강수", precip.get("annual_mean_mm"), "mm")}
  </table>

  <h2>4. 위험요인 분석</h2>
  <table>
    {_row("동해 위험도", "별도 현장 확인 필요")}
    {_row("고온·건조 스트레스", "별도 현장 확인 필요")}
    {_row("병해충 위험도", diag.get("병해충_취약도"))}
    {_row("관리 필요도", diag.get("관리_우선순위"))}
  </table>
  {_radius_rows("병해충 발생 이력", mg_radius.get("disease") or {})}
  {_radius_rows("조림 이력", mg_radius.get("planting") or {}, "main_species")}
  {_radius_rows("숲가꾸기 이력", mg_radius.get("tending") or {}, "main_work_type")}

  <h2>5. Top-3 추천 수종</h2>
  {''.join(rec_cards) if rec_cards else '<p>추천 결과 정보 없음</p>'}

  <h2>6. 추천 근거 설명</h2>
  <p>{escape(d["explanation"] or NO_INFO)}</p>

  <h2>7. 관리 방향</h2>
  <ul>
    <li>조림 전 현장 토심·배수·사면 방향을 재확인하세요.</li>
    <li>병해충 발생 이력이 있는 지역은 식재 후 모니터링을 강화하세요.</li>
    <li>최근 숲가꾸기 이력이 있는 지역은 기존 관리 방향과 충돌하지 않도록 계획을 조정하세요.</li>
  </ul>
  {_reliability_html(d["reliability"])}
  {_official_html(d)}
</body>
</html>"""


def _register_pdf_font() -> str:
    """Register a Korean-capable font when available; return font name."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = [
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("C:/Windows/Fonts/NanumGothic.ttf"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    ]
    for path in candidates:
        if path.exists():
            pdfmetrics.registerFont(TTFont("ForestKorean", str(path)))
            return "ForestKorean"
    return "Helvetica"


def create_pdf_report(result: dict) -> bytes:
    """Create a PDF report as bytes. Requires reportlab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        PageBreak,
    )

    font = _register_pdf_font()
    d = _collect_report_data(result)
    loc = d["loc"]
    site = d["site"]
    forest = d["forest"]
    site_info = d["site_info"]
    detail = d["detail"]
    observed = d["observed"]
    precip = d["precip"]
    diag = d["diag"]
    mg_radius = d["mg_radius"]

    styles = getSampleStyleSheet()
    title = ParagraphStyle("ForestTitle", parent=styles["Title"], fontName=font, fontSize=20, leading=26, textColor=colors.HexColor("#1B5E20"))
    h2 = ParagraphStyle("ForestH2", parent=styles["Heading2"], fontName=font, fontSize=13, leading=18, spaceBefore=10, textColor=colors.HexColor("#1B5E20"))
    body = ParagraphStyle("ForestBody", parent=styles["BodyText"], fontName=font, fontSize=9.5, leading=14)
    small = ParagraphStyle("ForestSmall", parent=body, fontSize=8.5, leading=12)

    def para(text, style=body):
        return Paragraph(escape(str(text)), style)

    def table(rows):
        data = [[para(label, small), para(_plain(value, suffix), small)] for label, value, suffix in rows]
        t = Table(data, colWidths=[42 * mm, 115 * mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9E2D9")),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F8E9")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        return t

    story = [
        Paragraph("Forest AI 분석 보고서", title),
        para("강원권 산림 입지 환경을 분석해 Top-3 수종 후보와 추천 근거를 정리한 의사결정 지원 보고서입니다."),
        Spacer(1, 8),
        Paragraph("1. 분석 위치", h2),
        table([
            ("위도", loc.get("lat"), ""),
            ("경도", loc.get("lon"), ""),
            ("분석일자", d["generated"], ""),
        ]),
        Paragraph("2. 현재 숲 정보", h2),
        table([
            ("임상", forest.get("임종"), ""),
            ("주요 수종", forest.get("수종"), ""),
            ("영급", forest.get("영급"), ""),
            ("경급", forest.get("경급"), ""),
            ("밀도", forest.get("밀도"), ""),
        ]),
        Paragraph("3. 입지 환경 분석", h2),
        table([
            ("고도", site.get("elevation_m"), "m"),
            ("경사", site.get("slope_deg"), "°"),
            ("사면방향", site.get("aspect_dir"), ""),
            ("기후대", site.get("climate_zone"), ""),
            ("토양형", site_info.get("토양형코드") or detail.get("토양형코드"), ""),
            ("토심", site_info.get("토심코드") or detail.get("유효토심"), ""),
            ("배수", detail.get("토양배수코드"), ""),
            ("평균기온", observed.get("temp_c"), "℃"),
            ("강수량", observed.get("precip_mm"), "mm"),
            ("격자 연강수", precip.get("annual_mean_mm"), "mm"),
        ]),
        Paragraph("4. 위험요인 및 반경 이력", h2),
        table([
            ("동해 위험도", "별도 현장 확인 필요", ""),
            ("고온·건조 스트레스", "별도 현장 확인 필요", ""),
            ("병해충 위험도", diag.get("병해충_취약도"), ""),
            ("관리 필요도", diag.get("관리_우선순위"), ""),
        ]),
    ]

    for label, data, key in [
        ("병해충 발생 이력", mg_radius.get("disease") or {}, ""),
        ("조림 이력", mg_radius.get("planting") or {}, "main_species"),
        ("숲가꾸기 이력", mg_radius.get("tending") or {}, "main_work_type"),
    ]:
        story.append(Paragraph(label, h2))
        lines = _radius_lines(data, key) if data else [NO_INFO]
        for line in lines:
            story.append(para("• " + line))

    story.append(Paragraph("5. Top-3 추천 수종", h2))
    for i, rec in enumerate(d["recs"][:3], 1):
        story.append(para(f"{i}. {_plain(rec.get('수종'))} ({_plain(rec.get('학명'))})", body))
        story.append(table([
            ("최종점수", rec.get("적합점수"), ""),
            ("유형", rec.get("유형"), ""),
            ("탄소흡수", rec.get("탄소흡수"), ""),
            ("추천 근거", " / ".join(rec.get("주요근거", [])[:4]) or NO_INFO, ""),
            ("위험/주의", " / ".join((rec.get("유의사항") or ["뚜렷한 감점 요인은 확인하지 않았습니다."])[:4]), ""),
        ]))

    story.extend([
        Paragraph("6. 추천 근거 설명", h2),
        para(d["explanation"] or NO_INFO),
        Paragraph("7. 관리 방향", h2),
        para("• 조림 전 현장 토심·배수·사면 방향을 재확인하세요."),
        para("• 병해충 발생 이력이 있는 지역은 식재 후 모니터링을 강화하세요."),
        para("• 최근 숲가꾸기 이력이 있는 지역은 기존 관리 방향과 충돌하지 않도록 계획을 조정하세요."),
    ])

    rel = d.get("reliability") or {}
    if rel:
        ov = rel.get("overall_reliability") or {}
        _head = {"높음": "추천 근거가 안정적인 구간", "보통": "현장 확인 권장 구간",
                 "낮음": "현장 확인 필요 구간", "분석 제한": "신뢰도 정보 제한"}.get(ov.get("level"), "신뢰도 분석")
        story.append(Paragraph("8. 추천 신뢰도 분석", h2))
        story.append(para(f"{_head} — {_plain(ov.get('message'))}"))
        for label, sub in (("SDM 확률 차이", rel.get("sdm_probability_gap")),
                           ("주변 임분 일치도", rel.get("neighbor_agreement")),
                           ("환경 다양성", rel.get("environment_diversity"))):
            sub = sub or {}
            story.append(para(f"• {label}: {_plain(sub.get('level'))} — {_plain(sub.get('message'))}"))

    aff = d.get("afforestation") or {}
    ff = d.get("forest_function") or {}
    ls = d.get("landslide") or {}
    if aff or ff or ls:
        off = (rel or {}).get("official_afforestation") or {}
        story.append(Paragraph("9. 공식 데이터 비교 · 재해", h2))
        if aff:
            story.append(para("• 공식 대표수종: " + (", ".join(aff.get("대표수종") or []) or NO_INFO)))
            if off.get("message"):
                story.append(para(f"• 공식 조림 일치: {_plain(off.get('level'))} — {_plain(off.get('message'))}"))
        if ff:
            story.append(para("• 공식 산림기능: " + _plain(ff.get("주기능"))
                              + (" (절대보전지역)" if ff.get("절대보전지역") else "")))
        if ls:
            story.append(para(f"• 산사태 위험등급(지점): {_plain(ls.get('point_grade'))}등급 "
                              f"{_plain(ls.get('point_label'))} · 반경 고위험 {(ls.get('high_risk_ratio') or 0) * 100:.0f}%"))

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Forest AI 분석 보고서",
    )
    doc.build(story)
    return buf.getvalue()


def report_filename(ext: str = "html") -> str:
    ext = ext.lstrip(".")
    return f"forest_ai_report_{datetime.now().strftime('%Y%m%d')}.{ext}"
