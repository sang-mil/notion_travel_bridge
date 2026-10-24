# Notion Travel Bridge

**Notion에 적은 여행 계획을 Gemini로 구조화하고, Google My Maps에 장소 핀을 만든 뒤, 완성된 지도 링크를 다시 Notion에 기록하는 Windows용 자동화 도구**입니다.

> 처음 사용하는 분은 이 README의 키 발급 방법부터 순서대로 진행하세요. 이미 설정한 사용자는 [Quick Start 실행](#5-quick-start-실행)으로 이동하면 됩니다.

## 주요 기능

- Notion 페이지에 자연어로 작성한 여행 계획 읽기
- Gemini API로 일정·장소·방문 순서 구조화
- Google My Maps 가져오기용 CSV 및 Google Maps 링크 생성
- 전용 Chrome 프로필로 Google My Maps 열기 및 CSV 가져오기 자동화
- 지도 URL과 재사용 가능한 여행 계획 템플릿을 원본 Notion 페이지에 기록
- Windows용 `QuickStart.bat` 메뉴 제공

## 작동 흐름

```text
Notion 여행 계획 페이지
        │
        ▼
main.py — 원문 읽기
        │
        ▼
Gemini API — 일정 구조화
        │
        ▼
analyze_itinerary.py → itinerary.json
        │
        ▼
build_map_links.py → map_import.csv / Google Maps 링크
        │
        ▼
publish_mymaps.py — Google My Maps 가져오기
        │
        ▼
sync_notion_results.py — 지도 링크와 템플릿 링크를 Notion에 기록
```

## 1. 필요한 것

- Windows 10 또는 Windows 11
- Python 3.10 이상 (64비트 권장)
- Google Chrome
- Notion 계정과 여행 계획 페이지
- Google AI Studio에서 발급한 Gemini API 키
- 인터넷 연결

이 프로젝트의 실행 메뉴는 Python 가상환경과 필요한 패키지를 자동으로 준비합니다. 최초 설치 때는 인터넷 연결이 필요합니다.

## 2. Gemini API 키 발급하기

Gemini API 키는 Google AI Studio에서 발급합니다. **Gemini 웹 앱 로그인과 Gemini API 키는 서로 다릅니다.**

1. [Google AI Studio API Keys](https://aistudio.google.com/apikey)를 엽니다.
2. Google 계정으로 로그인하고 약관이 나오면 확인합니다.
3. API 키 화면에서 **Create API key / API 키 만들기**를 선택합니다.
4. 기존 Google Cloud 프로젝트를 선택하거나 새 프로젝트를 생성하라는 안내에 따라 진행합니다.
5. 생성된 키를 복사해 안전한 곳에 잠시 보관합니다. 키를 공개 채팅, 스크린샷, GitHub 커밋에 포함하면 안 됩니다.
6. 사용량과 한도는 [Google AI Studio](https://aistudio.google.com/)에서 확인합니다.

### 무료로 사용할 수 있나요?

Gemini API는 모델, 계정, 지역, 사용량 제한에 따라 무료 등급이 제공될 수 있지만 **무제한 무료 사용을 보장하지 않습니다.** 실행 전에 [Gemini API 가격 및 무료 등급](https://ai.google.dev/gemini-api/docs/pricing)과 본인의 사용량/한도를 확인하세요. Google의 모델 및 요금 정책은 바뀔 수 있습니다.

현재 기본 모델은 `gemini-3.8-flash`입니다. 모델을 변경해야 한다면 `.env`의 `GEMINI_MODEL` 값을 [공식 모델 목록](https://ai.google.dev/gemini-api/docs/models)에서 본인 계정으로 사용할 수 있는 모델 ID로 바꾸세요.

## 3. Notion 통합 토큰 발급하기

`NOTION_TOKEN`은 Notion 페이지 주소가 아니라, 이 프로그램에 Notion API 접근 권한을 부여하는 **통합(Internal Integration) 토큰**입니다.

1. 사용할 워크스페이스에 로그인합니다. 조직 워크스페이스는 소유자/관리자 권한이 필요할 수 있습니다.
2. Notion에서 **설정(Settings) → 연결(Connections)**로 이동합니다. 화면에 따라 개발자 모드 또는 개발자 설정 메뉴가 보일 수 있습니다.
3. **새 연결(New connection)**을 만들고 알아보기 쉬운 이름(예: `Notion Travel Bridge`)을 입력합니다.
4. 사용할 워크스페이스를 선택하고 연결 생성을 완료합니다.
5. 생성한 연결의 설정/메뉴에서 **Internal Integration Token / 내부 연결 토큰**을 복사합니다. 이 값이 `.env`의 `NOTION_TOKEN`입니다.
6. 이 프로그램이 페이지를 읽고 결과를 기록할 수 있도록 통합 권한에서 **콘텐츠 읽기(Read content)**와 **콘텐츠 삽입/쓰기(Insert/Write content)** 권한을 활성화합니다. 권한 이름은 Notion UI 버전에 따라 조금 다를 수 있습니다.
7. 여행 계획 페이지를 엽니다. 페이지 오른쪽 위 `•••` 메뉴에서 **Connections / 연결** 또는 **Add connections / 연결 추가**를 선택합니다.
8. 방금 만든 `Notion Travel Bridge` 통합을 찾아 연결하고 권한을 확인합니다. **토큰만 발급하고 페이지를 통합과 연결하지 않으면 API 접근이 거부될 수 있습니다.**

공식 안내: [Notion API 통합 만들기](https://www.notion.com/ko/help/create-integrations-with-the-notion-api)

### Notion 페이지 ID 확인하기

1. 브라우저에서 프로그램이 읽을 여행 계획 페이지를 엽니다.
2. 주소창 URL을 복사합니다.
3. `.env`의 `NOTION_PAGE_ID`에 전체 URL을 넣으면 됩니다. 이 프로그램은 페이지 UUID만 넣는 방식도 지원합니다.
4. Notion 통합과 공유한 페이지가 URL에 해당하는 페이지인지 확인합니다.

예시 URL 형식:

```text
https://www.notion.so/워크스페이스/여행계획-0123456789abcdef0123456789abcdef
```

페이지 URL 전체를 그대로 넣어도 되고, 그 안의 32자리 페이지 ID 또는 하이픈이 포함된 UUID만 넣어도 됩니다.

## 4. 다운로드 및 설정

### 방법 A: GitHub에서 내려받기

Git이 설치되어 있다면 PowerShell에서 다음 명령을 실행합니다. `<저장소-주소>`는 이 프로젝트의 GitHub 저장소 주소로 바꿔 주세요.

```powershell
git clone <저장소-주소>
Set-Location .\NotionTravelBridge
```

Git을 사용하지 않는다면 GitHub 저장소의 **Code → Download ZIP**으로 내려받고 압축을 풉니다.

### `.env` 만들기

프로젝트 루트에 있는 `.env.example`을 복사해 `.env`를 만든 뒤 값을 입력합니다. Quick Start 메뉴 1번을 실행하면 `.env`가 없을 때 예시 파일을 복사하고 설정을 안내합니다.

PowerShell에서 직접 만들려면:

```powershell
Copy-Item .env.example .env
notepad .env
```

`.env`에는 다음과 같은 항목이 들어갑니다. 아래 값은 **예시/자리표시자**이므로 본인의 값으로 바꿔야 합니다.

```dotenv
# Notion Internal Integration token — 비밀로 유지
NOTION_TOKEN=여기에_본인의_Notion_통합_토큰

# 전체 Notion 페이지 URL 또는 페이지 UUID
NOTION_PAGE_ID=https://www.notion.so/워크스페이스/여행계획-여기에페이지ID

# Notion API 버전
NOTION_VERSION=2026-03-11

# Google AI Studio에서 발급한 Gemini API 키 — 비밀로 유지
GEMINI_API_KEY=여기에_본인의_Gemini_API_키

# Gemini API 모델 ID
GEMINI_MODEL=gemini-3.8-flash
```

저장 후 메모장을 닫습니다. `.env`는 비밀정보 파일이며 `.gitignore`에서 제외되어야 합니다. **실제 토큰이나 API 키를 README, 소스 코드, 공개 이슈, 스크린샷 또는 GitHub에 올리지 마세요.**

## 5. Quick Start 실행

1. `QuickStart.bat`과 `quick_start.ps1`이 같은 폴더에 있는지 확인합니다.
2. `QuickStart.bat`을 더블클릭합니다.
3. 첫 실행에서는 **1. 최초 설정 / 설치 상태 점검**을 선택합니다. 전용 `.venv` 가상환경과 Python 패키지, Playwright 브라우저를 준비하고 `.env` 항목을 확인합니다.
4. **2. Google My Maps 로그인 준비**를 선택합니다.
5. 열린 프로젝트 전용 Chrome 창에서 Google 계정으로 직접 로그인합니다. 2단계 인증이 필요하면 브라우저에서 직접 완료합니다.
6. 로그인이 끝나면 전용 Chrome 창을 완전히 닫고 Quick Start 창으로 돌아와 Enter를 누릅니다.
7. **3. 전체 실행**을 선택하고 확인 질문에 `Y`를 입력합니다.

### 메뉴 안내

| 번호 | 메뉴 | 동작 |
|---:|---|---|
| `1` | 최초 설정 / 설치 상태 점검 | Python, 의존성, Chrome, `.env` 확인 |
| `2` | Google My Maps 로그인 준비 | 전용 Chrome 프로필로 로그인 세션 준비 |
| `3` | 전체 실행 | Notion → Gemini → CSV → My Maps → Notion 결과 기록 |
| `4` | 기존 지도 결과만 Notion에 기록 | 기존 `output/mymaps_config.json`의 지도 링크를 Notion에 기록 |
| `5` | `.env` 설정 열기 | API 키와 페이지 ID를 메모장에서 수정 |
| `6` | 출력 폴더 열기 | 중간 결과 및 자동화 진단 스크린샷 확인 |
| `7` | 사용자 설명서 열기 | `docs` 폴더의 사용자 설명서 열기 |
| `0` | 종료 | 메뉴 닫기 |

## 6. Google My Maps에서 수동으로 확인할 수 있는 단계

Google My Maps 웹사이트의 화면이 바뀌면 자동화가 일부 버튼이나 열을 찾지 못할 수 있습니다. 이 경우 프로그램이 안내하는 동안 브라우저에서 직접 완료하면 됩니다.

1. 새 지도를 만들라는 안내가 나오면 브라우저에서 `Create`/`새 지도 만들기`를 누릅니다.
2. `가져오기(Import)`를 눌러 `output/map_import.csv`를 선택합니다.
3. 위치 지정 열 화면에서는 **`Map search query`**를 선택하고 계속 진행합니다.
4. 핀 제목 열 화면에서는 **`Place`**를 선택하고 `완료(Finish)`를 누릅니다.
5. 지도에 장소 핀이 표시되는지 확인합니다.
6. 터미널/PowerShell이 `브라우저에서 해당 단계를 직접 완료한 다음 Enter를 누르세요`라고 기다릴 때만 터미널을 클릭해 Enter를 누릅니다. 브라우저 안에서 Enter를 누르는 단계가 아닙니다.

핀 이름이 지도 위에 항상 표시되지는 않을 수 있습니다. 핀을 클릭해 정보창에 장소 이름이 나오는지 확인하세요.

같은 CSV를 이미 가져온 경우 자동화는 중복 업로드를 건너뛸 수 있습니다. 새 지도를 강제로 만들고 싶을 때는 프로젝트 폴더의 PowerShell에서 다음 명령을 사용할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe .\publish_mymaps.py --new-map
```

기존 지도를 지정하려면:

```powershell
$MapUrl = Read-Host "Google My Maps 편집 URL을 붙여넣으세요"
.\.venv\Scripts\python.exe .\publish_mymaps.py --map-url "$MapUrl"
```

기존 지도에서 레이어를 교체할 때는 현재 지도 URL이 맞는지 반드시 확인하세요. 기존 레이어의 장소 항목이 새 CSV 내용으로 교체될 수 있습니다.

## 7. 다음 여행 계획 만들기

1. 첫 실행이 끝나면 원본 Notion 여행 계획 페이지에 지도 링크와 재사용 템플릿 링크가 기록됩니다.
2. Notion에서 `✈️ 여행 계획 템플릿 (Notion Travel Bridge)` 페이지를 복제합니다.
3. 복제한 페이지에서 `[대괄호]` 안의 안내를 실제 일정으로 바꾸고, 사용하지 않는 예시는 삭제합니다.
4. `.env`의 `NOTION_PAGE_ID`를 새 여행 페이지의 URL 또는 ID로 변경합니다.
5. 새 페이지에도 Notion 통합을 연결했는지 확인합니다.
6. `QuickStart.bat`을 열어 메뉴 `3`을 실행합니다.

**중요:** `NOTION_PAGE_ID`를 바꾸지 않으면 이전에 설정한 페이지를 다시 처리합니다. 공개 템플릿을 사용하는 다른 사람도 본인의 API 키와 페이지 ID를 설정해야 합니다.

## 8. 생성되는 결과물

| 파일 | 내용 |
|---|---|
| `output/notion_input.json` | Notion에서 읽어 온 페이지 및 블록 정보 |
| `output/itinerary_text.txt` | Gemini 분석용 여행 원문 텍스트 |
| `output/itinerary.json` | Gemini가 구조화한 날짜별 여행 일정 |
| `output/map_import.csv` | Google My Maps에 가져올 장소 데이터 |
| `output/google_maps_links.md` | 장소 검색 및 방문 순서 링크 |
| `output/mymaps_config.json` | My Maps URL, CSV 해시, 마지막 가져오기 정보 |
| `output/notion_sync_config.json` | Notion 결과 기록 상태 및 생성한 템플릿 링크 |
| `output/browser_debug/` | 자동화 문제 발생 시 저장되는 화면 스크린샷 |

`output`에는 개인 여행 계획, 페이지 URL, 장소와 메모가 들어갈 수 있어 공개 저장소에 올리지 않도록 설정되어 있습니다.

## 9. 문제 해결

### Notion API 401 오류

- `.env`의 `NOTION_TOKEN`이 맞는지 확인합니다.
- 토큰에 앞뒤 공백이 없고 예시용 텍스트가 남아 있지 않은지 확인합니다.
- 토큰이 노출되었다면 Notion에서 폐기/재발급합니다.

### Notion API 403 또는 404 오류

- `NOTION_PAGE_ID`가 올바른 페이지인지 확인합니다.
- 해당 페이지가 통합에 연결되어 있는지 확인합니다.
- 통합에 콘텐츠 읽기 및 결과 기록 권한이 있는지 확인합니다.
- 복제한 새 페이지로 바꾸었다면 그 페이지에도 연결을 추가합니다.

### Gemini API 키 오류 / 할당량 초과 / 모델을 찾지 못함

- `GEMINI_API_KEY`가 Google AI Studio의 API 키인지 확인합니다.
- [API 사용량 및 가격](https://ai.google.dev/gemini-api/docs/pricing)을 확인합니다. 무료 한도는 계정·모델 및 정책에 따라 다릅니다.
- `GEMINI_MODEL`이 현재 사용 가능한 모델 ID와 정확히 일치하는지 확인합니다. 기본값은 `gemini-3.8-flash`입니다.
- 기존 `.env`에 `gemini-2.5-flash`가 남아 있으면 현재 계정에서 쓸 수 있는 모델 ID로 직접 바꿉니다.

### Google 로그인이 반복됨

- 메뉴 `2`로 연 **프로젝트 전용 Chrome**에서 로그인합니다.
- Google 계정 비밀번호와 인증 코드를 자동화 프로그램에 입력하지 마세요. 로그인 및 2단계 인증은 브라우저에서 직접 처리합니다.
- 로그인을 마친 뒤 그 전용 Chrome 창을 완전히 닫고 메뉴 `3`을 실행합니다.

### `Map search query` 또는 `Place` 열 선택 오류

- CSV 업로드 뒤 `Map search query`를 위치 지정 열로 선택합니다.
- 다음 화면에서 `Place`를 핀 제목 열로 지정하고 완료합니다.
- 지도에 핀이 보이면 터미널/PowerShell로 돌아가서 프로그램이 대기 중일 때 Enter를 누릅니다.
- 오류 화면은 `output/browser_debug/`에 저장됩니다.

### Python 또는 패키지 설치 오류

PowerShell에서 다음을 확인합니다.

```powershell
py -3 --version
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

Python 3.10 이상을 설치하고, 설치/다운로드가 끝날 때까지 인터넷 연결을 유지하세요. Google Chrome도 별도로 설치되어 있어야 합니다.

### 지도가 열리지만 핀 이름이 지도 위에 보이지 않음

핀을 클릭해 정보창의 제목을 확인하세요. 지도 라벨이 필요하면 My Maps의 레이어 스타일에서 `라벨 설정(Set labels)`을 `Place`로 지정할 수 있습니다.

### 오프라인 지도

이 프로젝트는 **온라인 Google My Maps 지도를 생성**합니다. 오프라인 지도를 다운로드하지 않으며, 사용자 지정 My Maps 레이어가 Google Maps 앱의 오프라인 영역에 똑같이 표시된다고 보장하지 않습니다.

## 10. 개인정보 및 보안

- `NOTION_TOKEN`과 `GEMINI_API_KEY`는 비밀번호처럼 취급하세요.
- `.env`, `.mymaps_browser_profile/`, `.venv/`, `output/`의 실제 결과 파일을 GitHub에 커밋하지 마세요.
- 여행 원문은 Gemini API로 전송되어 분석됩니다. 개인정보, 예약 번호, 여권 번호처럼 분석에 필요하지 않은 민감정보는 여행 페이지에 쓰지 마세요.
- Google 로그인은 전용 브라우저에서 사용자가 직접 진행합니다. 이 프로그램은 Google 계정 비밀번호를 수집하지 않습니다.
- Google My Maps는 위치를 잘못 매칭할 수 있습니다. 여행 전에 핀 위치, 이동 경로, 운영 시간, 휴무일, 예약 조건을 직접 확인하세요.
- 키가 GitHub 등에 실수로 올라갔다면 커밋 이력을 단순히 지우는 것만으로 해결되지 않을 수 있습니다. 해당 키를 즉시 폐기/재발급하고, 저장소 기록도 정리하세요.

## 참고 문서

- [Google AI Studio — API 키 만들기](https://aistudio.google.com/apikey)
- [Gemini API — API 키 사용](https://ai.google.dev/gemini-api/docs/api-key?hl=ko)
- [Gemini API — 모델 목록](https://ai.google.dev/gemini-api/docs/models?hl=ko)
- [Gemini API — 가격 및 무료 등급](https://ai.google.dev/gemini-api/docs/pricing?hl=ko)
- [Notion — API 통합 만들기 (한국어)](https://www.notion.com/ko/help/create-integrations-with-the-notion-api)
- [Notion Developers](https://developers.notion.com/)
- [사용자 설명서 (HTML)](docs/사용자_설명서.html)
- [사용자 설명서 (Markdown)](docs/사용자_설명서.md)
- [Notion 여행 계획 템플릿](templates/notion_travel_plan_template.md)

## 라이선스

이 프로젝트의 자체 코드와 문서는 [MIT License](LICENSE)로 배포합니다. MIT 라이선스는 저작권 및 라이선스 고지를 유지하는 조건으로 사용, 수정, 재배포, 상업적 이용을 허용합니다. 보증은 제공되지 않습니다.

Copyright (c) 2026 sang-mil

이 라이선스는 Google, Notion 등의 서비스, 해당 상표, API, 계정 또는 별도 Python 패키지에 대한 권리를 부여하지 않습니다. 각 서비스의 이용약관과 각 의존성 패키지의 라이선스는 별도로 적용됩니다. 이 프로그램은 외부 서비스의 변경이나 API 사용량/요금에 대해 보증하지 않습니다.
