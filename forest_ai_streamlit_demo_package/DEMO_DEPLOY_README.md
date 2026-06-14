# Forest AI Streamlit Demo Deploy

이 패키지는 무료 Streamlit Cloud 배포를 위한 데모모드 버전입니다.

## 특징

- 대용량 GIS 데이터 파일을 포함하지 않습니다.
- `data/`, `.venv`, GeoPackage, DEM 파일 없이 실행됩니다.
- 현재 위치 GPS, 사진 EXIF GPS, 좌표 직접 입력을 지원합니다.
- 좌표 기반 데모 분석, Top-3 수종 추천, 자연어 보고서, HTML 보고서 다운로드를 제공합니다.
- Gemini API 키가 없거나 실패해도 규칙 기반 보고서가 출력됩니다.

## 실행 명령어

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud 설정

무료 Streamlit Cloud에는 이 폴더의 파일만 올리면 됩니다.

```text
app.py
requirements.txt
.streamlit/config.toml
app/mobile_demo.py
forest_reco/demo_pipeline.py
forest_reco/exif_gps.py
forest_reco/version.py
forest_reco/__init__.py
```

## 주의

이 버전은 시연 안정성을 위한 데모모드입니다.
실제 임상도, DEM, RF-SDM 모델, 병해충 공간정보를 직접 조회하는 버전은 원본 프로젝트의 전체 데이터 패키지가 필요합니다.
