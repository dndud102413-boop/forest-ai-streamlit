# 🌲 산림 수종 추천 AI (forest_reco)

> 사진을 찍으면 그 위치(위·경도)를 읽어, **거기에 심기 적합한 나무 수종**을 추천하고
> 그 이유를 설명하는 모바일 프로토타입.
>
> 원본 Colab 노트북(모바일 산림 스캐닝 AI)을 분석·리팩토링하여, 실행 불가능했던
> 치명 버그를 고치고 **목표(식재 수종 추천)** 에 맞는 엔진을 새로 구축했습니다.
> 원본 분석/결함은 [`ANALYSIS.md`](ANALYSIS.md) 참고.

---

## 문서 안내
| 우선 | 문서 | 내용 |
|---|---|---|
| ⭐ | [00_START_HERE.md](00_START_HERE.md) | **여기부터** — 1분 요약·현재 수준·읽기 지도·압축 전달법 |
| ⭐ | [변경사항_리포트.md](변경사항_리포트.md) | **쉬운 말**로 무엇을 왜 바꿨나(비유·예시 중심) |
| 🔧 | [COLAB_가이드.md](COLAB_가이드.md) | Colab에서 이어서 개발하는 방법(업로드·수정·실행) |
| 🧪 | [테스트_가이드.md](테스트_가이드.md) | 기능별 테스트 방법(자동 + 직접 실행) |
| 📖 | [개발자_전달.md](개발자_전달.md) | 종합 레퍼런스(적용·데이터·모델·로드맵·전달멘트) |
| 🔬 | [진단_리포트.md](진단_리포트.md) · [ANALYSIS.md](ANALYSIS.md) | 견고성 재진단 · 원본 정밀 분석 |

## 핵심 아이디어

```
 사진(EXIF GPS) / 현재 GPS / 좌표 입력
        │
        ▼
 ┌─────────────────────────────────────────────┐
 │  임상도(벡터 폴리곤) ─ point-in-polygon ─→ 임분 속성│
 │  DEM(래스터) ─ 셀 샘플링(CRS변환·경계검사) ─→ 고도/경사/향│
 └─────────────────────────────────────────────┘
        │
        ▼
 기후대 판정(위도+고도) ──┐
 인접 임분 수종 빈도(경험적)─┤→  하이브리드 적지적수 추천  →  Top-N 수종 + 근거
        │                                                │
        ▼                                                ▼
                                            Gemini LLM 설명(없으면 오프라인 폴백)
```

- **추천 = 데이터기반 ML(SDM) + 지식기반 적지적수 점수 + 경험적 근거 (하이브리드)**
  - ML(SDM): 임상도 실분포로 학습한 `P(수종|환경)`. **기본 사용**, 모델 신뢰도(f1)에 비례해 가중.
  - 지식기반: 34개 주요 수종의 적지적수(기후대·고도·경사·향·내건/내한·용도) 점수 — 설명·콜드스타트.
  - 경험적: 임상도 인접 임분에서 실제로 우점하는 수종일수록 가점("실제로 잘 자란다"는 증거).
- 블랙박스 ML이 아니라 **요인별 근거가 보이는 투명한 점수**라 시민·산주·공무원·연구자
  모두에게 "왜 이 수종인가"를 설명할 수 있습니다.

---

## 빠른 시작 (로컬 — 데이터 없어도 동작)

```bash
pip install -r requirements.txt

# 콘솔 데모 (합성 강원권 데이터 자동 생성)
python scripts/run_demo.py --lat 37.95 --lon 127.66 --goal 탄소흡수 --mock

# 모바일 웹앱  (Windows: run_app.bat 더블클릭)
streamlit run app/streamlit_app.py

# 정식 앱 연결용 REST API  (Windows: run_api.bat) — 문서 http://localhost:8000/docs
uvicorn app.api:app --port 8000
```
앱 사이드바에서 **데모 모드** 토글을 켜면 합성 데이터로, 끄고 실데이터 폴더를
지정하면 실데이터로 동작합니다. 같은 와이파이의 휴대폰에서 `http://<PC-IP>:8501` 로
접속하면 모바일 화면을 그대로 테스트할 수 있습니다.

### 위치 입력 4가지
🖼 **사진 업로드**(갤럭시 등 위치 켜고 찍은 사진의 EXIF GPS 자동 인식) ·
📸 **즉석 촬영**(앱 내 카메라) · 🛰 **현재 위치**(브라우저 GPS) · 🗺 **좌표 직접**.

### 데이터기반 모델(SDM, 기본 사용)
임상도 실분포로 학습한 모델([sdm.py](forest_reco/sdm.py))이 추천에 **기본 반영**됩니다
(`use_sdm=True`, 앱 토글 ON). 영향력은 **모델 신뢰도(f1)에 비례해 자동 조절** — 데이터가
좋을수록 ML이 추천을 주도하고, 부족하면 지식기반이 받쳐줍니다. 끄려면 `use_sdm=False`.
자세한 배경은 [개발자_전달.md §8](개발자_전달.md).

## 빠른 시작 (Colab — 실데이터)

`colab_notebook.ipynb` 를 Colab에서 열고 위에서부터 실행하세요. Drive의
`Forest_AI/data/`(51_1.shp, 51_2.shp, gangwon_dem.tif)를 사용합니다.

---

## 프로젝트 구조

```
wooyoung/
├── forest_reco/                 # 코어 패키지
│   ├── config.py                # 경로/좌표계 상수 (Colab·로컬 자동 인식)
│   ├── geo.py                   # ★ CRS 변환 + 래스터 셀 샘플링(경계검사/nodata) + 경사/향
│   ├── exif_gps.py              # 사진 EXIF → 위경도 (부호/HEIC/누락 처리)
│   ├── forest_map.py            # 임상도(벡터) 적재·위치질의(sindex)·인접 수종빈도
│   ├── terrain.py               # DEM(래스터) 고도/경사/향 질의
│   ├── climate.py               # 위도·고도 기반 기후대(난대~한대) 판정
│   ├── species_db.py            # 적지적수 수종 KB 로더 (data/species_db.json)
│   ├── recommender.py           # ★ 하이브리드 식재 수종 추천 엔진(심을 나무)
│   ├── diagnosis.py             # 현재 숲 진단(생육/병해충/관리, 투명 규칙)
│   ├── llm.py                   # Gemini 설명 + 오프라인 템플릿 폴백
│   ├── sdm.py                   # ★ 수종분포모델(임상도 실관측 학습, 올바른 ML 대안)
│   ├── pipeline.py              # end-to-end analyze()
│   ├── mockdata.py              # 합성 임상도/DEM 생성(데이터 없이 구동)
│   └── data/species_db.json     # 34개 수종 적지적수 지식베이스
├── app/
│   ├── streamlit_app.py         # 모바일 반응형 앱(사진업로드/촬영/GPS/좌표)
│   └── api.py                   # ★ FastAPI REST API(정식 앱 연결용)
├── run_app.bat / run_api.bat    # Windows 원클릭 실행
├── scripts/
│   ├── prepare_data.py          # DEM merge / clip / inspect (노트북 정비 셀 대체)
│   └── run_demo.py              # 콘솔 데모
├── tests/                       # pytest (53 케이스)
├── docs/research/               # 도메인 연구 산출물(수종/스키마/기후/감사)
├── colab_notebook.ipynb         # 정리된 Colab 워크플로
├── ANALYSIS.md                  # 원본 노트북 분석/결함/개선
├── requirements.txt
└── README.md
```

---

## 실데이터 사용법

1. 원천 데이터를 준비합니다.
   - 임상도: `51_1.shp`(+ `.dbf/.shx/.prj`), `51_2.shp` … (강원=코드 51, EPSG:5179)
   - DEM: 여러 타일(`1.tif`~`7.tif` 등) → 1개로 병합

2. 데이터 정비 (`scripts/prepare_data.py`):
   ```bash
   # (a) DEM 타일 병합 → data/gangwon_dem.tif
   python scripts/prepare_data.py merge-dem --in "../*.tif" --out data/gangwon_dem.tif

   # (b) 임상도 경량화(컬럼축소+단순화+강원 crop) → data/gangwon_forest_light.gpkg
   #     원본 약 2GB → ~170MB. 메모리 안전(배치). 앱이 이 gpkg를 자동 우선 사용.
   python scripts/prepare_data.py light-gpkg \
          --shp data/51_1.shp data/51_2.shp --out data/gangwon_forest_light.gpkg --tolerance 30

   # (선택) 메타 점검
   python scripts/prepare_data.py inspect --shp data/51_1.shp --dem data/gangwon_dem.tif
   ```
   → `data/`에 `gangwon_dem.tif` + `gangwon_forest_light.gpkg`가 있으면 데모 모드를 꺼도
   실데이터로 동작합니다(앱은 실데이터 감지 시 자동으로 실데이터 모드로 시작).

3. 환경변수로 경로/파일명 지정(선택):
   ```bash
   export FOREST_RECO_DATA_DIR=/path/to/data
   export FOREST_RECO_SHP="51_1.shp,51_2.shp"   # 지정 시 경량 gpkg 자동선택보다 우선
   export FOREST_RECO_DEM="gangwon_dem.tif"
   export GEMINI_API_KEY="..."   # 없으면 오프라인 설명
   ```

> **좌표계 주의**: 임상도는 보통 EPSG:5179(UTM-K)지만 배포본에 따라 **5181**일 수
> 있습니다. 코드는 `.prj`에서 CRS를 읽으므로 별도 설정이 필요 없지만, `.prj`가 없으면
> `config.forest_crs_fallback`(기본 5179)이 적용됩니다.

---

## 타겟 사용자별 모드

| 대상 | 앱에서 | 설명 어조 |
|---|---|---|
| 일반 시민 | 사진 한 장 → 자동 추천 | 쉬운 말 3~5문장 |
| 산주(임야 소유자) | 좌표·목적(용재/탄소…) 지정 | 식재 실익 중심 5~7문장 |
| 산림 공무원 | 상세 데이터(JSON) 열람 | 표준용어·근거 6~8문장 |
| 연구자 | 요인별 점수/원시값 확인 | 정량적 8~10문장 |

설명 대상(`audience`)에 따라 LLM 프롬프트 어조가 바뀝니다.

---

## 모바일 배포(프로토타입)

원본처럼 Colab + cloudflared 로 외부 접속 URL을 만들 수 있습니다.
```bash
streamlit run app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0 &
./cloudflared tunnel --url http://localhost:8501
```
GPS 자동 인식은 브라우저 권한이 필요합니다. 사진 EXIF·수동 좌표 입력은 항상 동작합니다.
정식 모바일 앱은 이 추천 엔진을 REST API로 노출하고 Flutter/React Native에서 호출하는
것을 권장합니다(파이프라인이 순수 함수라 그대로 서버화 가능).

---

## 테스트

```bash
python -m pytest tests/ -q     # 53 passed
```
EXIF 부호 처리, 래스터 경계검사, 기후대 판정, 추천 랭킹, end-to-end 파이프라인을 검증합니다.

---

## 한계와 주의

- 수종 KB(고도·기후대 범위)는 산림청 적지적수·문헌 기반의 **합리적 추정치**입니다.
  실제 식재 전 현장 토양·배수 조사를 권장합니다(`docs/research/species_db` 출처 노트 참조).
- 기후대는 1점 GPS만으로는 온량지수를 직접 못 구해 **위도+고도 proxy**로 근사합니다.
  인근 기상관측 평년값이 있으면 더 정확합니다.
- LLM 설명은 보조 수단이며, 추천 결정 자체는 결정론적 엔진이 담당합니다.
