"""
api.py — 식재 수종 추천 REST API (FastAPI)

정식 모바일 앱(Flutter/React Native/네이티브)이 호출할 수 있는 백엔드. 추천 엔진이
순수 함수라 그대로 API로 노출된다. 모바일 앱은 (1) 사진 업로드 또는 (2) 위경도를
보내고, JSON 결과(입지·추천수종·설명)를 받는다.

실행:
    uvicorn app.api:app --host 0.0.0.0 --port 8000 --reload
    문서: http://localhost:8000/docs  (Swagger UI 자동 생성)

환경변수:
    FOREST_RECO_USE_MOCK=1   합성 데이터로 구동(기본). 0이면 실데이터 폴더 사용.
    GEMINI_API_KEY=...       있으면 LLM 설명, 없으면 오프라인 폴백.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from forest_reco.pipeline import analyze, DataSources
from forest_reco.recommender import GOALS
from forest_reco.llm import AUDIENCES
from forest_reco.species_db import default_db

app = FastAPI(
    title="산림 수종 추천 API",
    version="0.2.0",
    description="위치/사진 기반 식재 적합 수종 추천 + 입지 분석 + LLM 설명",
)
# 모바일 앱(다른 오리진)에서 호출 가능하도록 CORS 허용
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_USE_MOCK = os.environ.get("FOREST_RECO_USE_MOCK", "1") not in ("0", "false", "False")
# 데이터/모델 1회 로딩(프로세스 수명 동안 캐시)
_SOURCES = DataSources(use_mock=_USE_MOCK)


class AnalyzeBody(BaseModel):
    lat: float
    lon: float
    goal: Optional[str] = None
    audience: str = "시민"
    top_k: int = 6
    use_sdm: bool = True       # 데이터기반 ML(SDM) 기본 사용(신뢰도 비례 가중)
    explain: bool = True


@app.get("/health")
def health():
    return {"status": "ok", "use_mock": _USE_MOCK, "species": len(default_db())}


@app.get("/meta")
def meta():
    """앱에서 드롭다운 등을 채우기 위한 메타."""
    return {"goals": list(GOALS.keys()), "audiences": list(AUDIENCES.keys())}


@app.get("/species")
def species():
    """수종 지식베이스 전체."""
    db = default_db()
    return {
        "count": len(db),
        "species": [
            {
                "korean_name": s.korean_name, "scientific_name": s.scientific_name,
                "leaf_type": s.leaf_type, "climate_zones": s.climate_zones,
                "elev_min_m": s.elev_min_m, "elev_max_m": s.elev_max_m,
                "purposes": s.purposes, "carbon_seq": s.carbon_seq,
            }
            for s in db
        ],
    }


@app.post("/analyze")
def analyze_coords(body: AnalyzeBody):
    """위경도로 분석."""
    res = analyze(
        lat=body.lat, lon=body.lon, goal=body.goal, audience=body.audience,
        top_k=body.top_k, sources=_SOURCES,
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
        explain=body.explain, use_sdm=body.use_sdm,
    )
    if not res["ok"]:
        raise HTTPException(status_code=422, detail=res["message"])
    return res


@app.post("/analyze/photo")
async def analyze_photo(
    file: UploadFile = File(..., description="위치정보(EXIF GPS) 포함 사진"),
    goal: Optional[str] = Form(None),
    audience: str = Form("시민"),
    top_k: int = Form(6),
    use_sdm: bool = Form(True),
    lat: Optional[float] = Form(None),   # 사진에 GPS가 없을 때 폴백 좌표
    lon: Optional[float] = Form(None),
):
    """사진 업로드로 분석(EXIF GPS 자동 추출, 없으면 lat/lon 폴백)."""
    data = await file.read()
    res = analyze(
        photo=data, lat=lat, lon=lon, goal=goal, audience=audience,
        top_k=top_k, sources=_SOURCES,
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
        use_sdm=use_sdm,
    )
    if not res["ok"]:
        raise HTTPException(status_code=422, detail=res["message"])
    return res
