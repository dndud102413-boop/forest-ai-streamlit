"""
forest_reco — 위치 기반 식재 적합 수종 추천 엔진
==================================================

원본 Colab 노트북(모바일 산림 스캐닝 AI)을 리팩토링/확장한 패키지.

핵심 흐름:
    사진(EXIF GPS) 또는 위경도 입력
      → 임상도(벡터 폴리곤) + DEM(래스터)에서 입지 환경 추출
      → 기후대 판정
      → 적지적수 지식기반 점수 + 임상도 인접 경험적 빈도(하이브리드) 추천
      → Gemini LLM(또는 오프라인 템플릿) 자연어 설명

서브모듈:
    config       경로/좌표계 상수, 환경 설정
    geo          좌표계 안전 변환 + 래스터 셀 샘플링(경계검사/nodata) + 경사/향
    exif_gps     휴대폰 사진 EXIF → 위경도
    forest_map   임상도(벡터) 적재 및 위치 질의(공간 인덱스)
    terrain      DEM(래스터) 고도/경사/향 질의
    climate      위도·고도 기반 기후대 판정
    species_db   적지적수 수종 지식베이스
    recommender  하이브리드 식재 수종 추천 엔진
    llm          Gemini 연결 + 오프라인 폴백 설명
    pipeline     end-to-end 분석 파이프라인
    mockdata     실데이터 없이 동작하는 합성 임상도/DEM
"""

from .version import __version__

__all__ = ["__version__"]
