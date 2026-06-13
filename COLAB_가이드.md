# Colab에서 이어서 개발하기 (초기 개발자용 가이드)

> 제가 업데이트한 버전을 받아 **구글 Colab에서 작업을 이어가는** 방법입니다.
> 기존엔 노트북 한 칸 한 칸에 코드가 흩어져 있었지만, 이제 **`forest_reco` 파이썬 패키지**로
> 정리돼 있어 *노트북은 호출만* 하고 *로직은 패키지에서* 수정합니다. (Codex와도 잘 맞습니다)

---

## 0. 한 장 요약
1. 받은 폴더(`wooyoung`)를 **구글 드라이브에 업로드**.
2. Colab에서 [`colab_notebook.ipynb`](colab_notebook.ipynb) 열고 위에서부터 실행.
3. 기능을 바꾸려면 `forest_reco/` 안의 **해당 모듈 파일**을 수정(드라이브에서 직접/Codex).
4. 데이터는 `Forest_AI/data/`(임상도·DEM)에 두고, 없으면 **데모 모드(합성)** 로 그대로 동작.

---

## 1. 업데이트 버전을 Colab으로 가져오기 (3가지 중 택1)

### 방법 A — 드라이브 업로드(가장 쉬움, 추천)
1. 받은 zip을 풀어 `wooyoung` 폴더를 **내 드라이브 `MyDrive/Forest_AI/wooyoung`** 에 업로드.
2. Colab 첫 셀:
   ```python
   from google.colab import drive; drive.mount('/content/drive')
   import sys; sys.path.insert(0, '/content/drive/MyDrive/Forest_AI/wooyoung')
   ```

### 방법 B — GitHub(버전관리·협업에 가장 좋음)
1. 이 폴더를 GitHub 저장소에 올림(아래 §5 참고).
2. Colab:
   ```python
   !git clone https://github.com/<당신>/<repo>.git /content/wooyoung
   import sys; sys.path.insert(0, '/content/wooyoung')
   ```
   수정 후 `!git pull` 로 갱신, 또는 Colab에서 편집 후 `!git commit/push`.

### 방법 C — 직접 업로드(빠른 1회성)
   ```python
   from google.colab import files; files.upload()   # zip 올리고
   !unzip -q wooyoung.zip -d /content/wooyoung
   import sys; sys.path.insert(0, '/content/wooyoung')
   ```

---

## 2. 의존성 설치 (Colab 첫 셀에서 1회)
```python
!pip install -q geopandas rasterio pyproj shapely pillow scikit-learn streamlit streamlit-js-eval google-genai piexif fastapi "uvicorn[standard]" python-multipart
```
> Colab은 대부분 미리 깔려 있어 빠릅니다. (requirements.txt와 동일 목록)

---

## 3. 데이터 연결
```python
import os
# 실데이터(임상도/DEM)가 있으면:
os.environ['FOREST_RECO_DATA_DIR'] = '/content/drive/MyDrive/Forest_AI/data'
#   └ 이 폴더에 51_1.shp(+dbf/shx/prj), 51_2.shp, gangwon_dem.tif
```
- **데이터가 없거나 테스트만 할 땐** `DataSources(use_mock=True)` 로 합성 데이터 자동 생성.
- 여러 DEM 타일이면 먼저 병합:
  ```python
  !python /content/wooyoung/scripts/prepare_data.py merge-dem \
      --in "/content/drive/MyDrive/Forest_AI/data/*.tif" \
      --out /content/drive/MyDrive/Forest_AI/data/gangwon_dem.tif
  ```

---

## 4. 실행 — 두 가지 방식

### (a) 패키지를 직접 호출 (분석·디버깅에 최적)
```python
from forest_reco.pipeline import analyze, DataSources

src = DataSources(use_mock=True)          # 실데이터면 use_mock=False
res = analyze(lat=37.95, lon=127.66, goal='탄소흡수', audience='산주',
              sources=src, use_sdm=True)   # use_sdm=True → ML(SDM) 반영
print('현재 숲 진단:', res['diagnosis'])
for r in res['recommendations']:
    print(r['수종'], r['적합점수'], r['주요근거'][:2])
print(res['explanation']['text'])
```

### (b) 모바일 앱을 Colab에서 띄우기 (cloudflared 터널)
```python
!wget -q -nc https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared
!chmod +x cloudflared
import subprocess, os
subprocess.Popen(['streamlit','run','/content/wooyoung/app/streamlit_app.py',
                  '--server.port','8501','--server.address','0.0.0.0'])
import time; time.sleep(8)
```
다음 셀에서 터널 URL을 엽니다: `!./cloudflared tunnel --url http://localhost:8501`
> 정리된 흐름은 [`colab_notebook.ipynb`](colab_notebook.ipynb)에 그대로 들어 있습니다.

---

## 5. 기능을 바꾸려면 — 어디를 수정하나 (모듈 지도)

| 바꾸고 싶은 것 | 파일 |
|---|---|
| 추천 점수 로직·가중치 | `forest_reco/recommender.py` |
| 수종 지식베이스(추가/수정) | `forest_reco/data/species_db.json` |
| 현재 숲 진단 규칙 | `forest_reco/diagnosis.py` |
| ML 모델(알고리즘·피처) | `forest_reco/sdm.py` |
| 좌표계·래스터 샘플링 | `forest_reco/geo.py` |
| 사진 GPS 추출 | `forest_reco/exif_gps.py` |
| 기후대 판정 | `forest_reco/climate.py` |
| 전체 분석 흐름 | `forest_reco/pipeline.py` |
| 앱 화면 | `app/streamlit_app.py` |
| REST API | `app/api.py` |

**수정 후엔 반드시 테스트**: `!python -m pytest /content/wooyoung -q` (방법은 [테스트_가이드.md](테스트_가이드.md))

> Colab에서 `forest_reco`를 수정한 뒤 이미 import 했다면 런타임 재시작(또는
> `import importlib; importlib.reload(...)`)이 필요합니다. 모듈을 자주 고치면
> **로컬/깃에서 편집 → Colab에서 git pull** 흐름이 가장 깔끔합니다.

### Codex와 함께 쓰기
- Codex에게 "이 파일(`forest_reco/recommender.py`)에서 OO를 바꿔줘"처럼 **파일 단위**로 요청하면
  됩니다(노트북 셀이 아니라 모듈 단위라 Codex가 다루기 훨씬 쉽습니다).
- 변경 후 `pytest`로 회귀 확인 → 통과하면 반영. (테스트가 안전망 역할)

---

## 6. 자주 겪는 함정 (체크리스트)
- ❗ **좌표계**: 임상도가 5181 배포본인데 `.prj`가 없으면 코드가 경고/에러를 냅니다. `inspect`로
  먼저 확인하세요(아래).
- ❗ **데이터 범위 밖 좌표**: 강원권 밖을 넣으면 "데이터 없음"이 정상입니다(버그 아님).
- ❗ **첫 SDM 사용은 수십 초** 학습 후 캐시됩니다. 반복 호출은 빠릅니다.
- ❗ **Gemini 키 없음**: 자동으로 오프라인 설명으로 대체됩니다(에러 아님).

```python
# 실데이터 받으면 가장 먼저:
!python /content/wooyoung/scripts/prepare_data.py inspect \
    --shp $FOREST_RECO_DATA_DIR/51_1.shp --dem $FOREST_RECO_DATA_DIR/gangwon_dem.tif
```
