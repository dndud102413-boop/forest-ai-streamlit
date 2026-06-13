# Streamlit Cloud 배포 순서

이 문서는 휴대폰 LTE나 다른 와이파이에서도 Forest AI 앱을 실행하기 위한 배포 안내입니다.

## 1. 먼저 알아둘 점

현재 PC 주소인 `http://192.168...:8501`은 같은 와이파이 안에서만 접속됩니다.

Streamlit Cloud에 배포하면 아래처럼 인터넷 주소가 생깁니다.

```text
https://원하는-앱-이름.streamlit.app
```

이 주소는 아이폰 LTE, 다른 와이파이, 다른 사람 휴대폰에서도 열 수 있습니다.

## 2. 첫 배포는 데모 모드로 진행

이 프로젝트의 원본 산림 데이터에는 1GB가 넘는 파일이 여러 개 있습니다. GitHub와 Streamlit Cloud에 그대로 올리기에는 너무 큽니다.

그래서 첫 배포는 앱이 자동으로 만드는 합성 강원권 데이터로 실행합니다. 기능 테스트, 카메라 테스트, GPS 테스트에는 이 방식이 가장 빠르고 안정적입니다.

## 3. GitHub에 올릴 파일

`wooyoung` 폴더를 GitHub 저장소로 올립니다.

올라가야 하는 핵심 파일은 다음입니다.

```text
app.py
requirements.txt
app/streamlit_app.py
forest_reco/
README.md
.streamlit/config.toml
```

`data/`, `.venv/`, `__pycache__/`, `.tmp/` 같은 폴더는 올리지 않습니다. `.gitignore`가 이미 대부분 제외합니다.

## 4. Streamlit Cloud에서 앱 만들기

1. https://share.streamlit.io 접속
2. GitHub 계정으로 로그인
3. `Create app` 클릭
4. `Yup, I have an app` 선택
5. GitHub 저장소 선택
6. Branch는 보통 `main`
7. Main file path는 아래처럼 입력

```text
app.py
```

8. 필요하면 App URL에 원하는 이름 입력
9. `Deploy` 클릭

몇 분 기다리면 `https://...streamlit.app` 주소가 생깁니다.

## 5. Gemini API Key를 쓰는 경우

Gemini 설명 기능을 쓰려면 GitHub에 키를 올리지 말고, Streamlit Cloud의 `Advanced settings` 또는 앱 설정의 `Secrets`에 넣습니다.

```toml
GEMINI_API_KEY = "여기에_키_입력"
```

키가 없어도 앱은 자동 요약 설명으로 동작합니다.

## 6. 휴대폰 테스트

배포 주소를 아이폰 Safari나 Chrome에서 엽니다.

권장 테스트 순서:

1. `숲 사진` 탭 열기
2. `현장에서 바로 촬영` 누르기
3. 카메라 권한 허용
4. 위치 권한 허용
5. 사진 위치정보가 없으면 `현재 GPS를 이 사진의 분석 위치로 사용` 선택
6. `적합 수종 분석하기` 실행

## 7. 나중에 실데이터 배포로 확장

실데이터까지 배포하려면 큰 `.gpkg`, `.tif`, `.shp` 파일을 그대로 GitHub에 올리기보다 다음 중 하나를 선택하는 것이 좋습니다.

- 데이터 범위를 더 작게 잘라서 100MB 이하 파일로 만들기
- 외부 저장소에서 앱 시작 시 다운로드하기
- 유료/전용 서버에 데이터와 앱을 같이 올리기

첫 목표는 데모 배포 링크를 성공시키는 것입니다.

## 8. 데스크탑과 같은 실데이터로 Cloud 실행하기

데스크탑의 SDM 참고 성능 `f1=0.404`는 아래 데이터 조합으로 계산된 값입니다.

```text
data/gangwon_forest_light.gpkg
data/gangwon_dem.tif
data/gangwon_site_light.gpkg
data/gangwon_precip_2020_2024.tif
data/stations.csv
data/derived/stations_verified.csv
```

이 중 `gangwon_forest_light.gpkg`와 `gangwon_site_light.gpkg`는 GitHub 일반 저장소에 직접 올리기에는 큽니다.

따라서 실데이터 배포는 다음 방식으로 진행합니다.

1. 위 파일들을 zip으로 묶습니다.
2. GitHub Release, Google Drive 직접 다운로드 링크, S3 같은 외부 저장소에 올립니다.
3. Streamlit Cloud 앱 설정의 `Secrets`에 아래 값을 넣습니다.

```toml
FOREST_RECO_DATA_BUNDLE_URL = "https://데이터_번들_다운로드_URL/forest_reco_data.zip"
```

앱은 시작할 때 이 zip을 내려받아 `FOREST_RECO_DATA_DIR`에 풀고, 데모 모드가 아니라 실데이터 모드로 실행합니다.

GitHub 일반 저장소는 100MiB보다 큰 파일을 막으므로, 큰 `.gpkg` 파일은 코드 저장소가 아니라 Release/외부 저장소로 분리하는 것이 안전합니다.
