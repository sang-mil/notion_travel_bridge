from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

ROOT = Path(__file__).resolve().parent
INPUT_PATH = ROOT / "output" / "itinerary_text.txt"
OUTPUT_PATH = ROOT / "output" / "itinerary.json"

SCHEMA = {
    "type": "object",
    "properties": {
        "trip_title": {"type": "string"},
        "destination": {"type": "string"},
        "days": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "day_number": {"type": "integer"},
                    "date": {"type": "string"},
                    "area": {"type": "string"},
                    "places": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "order": {"type": "integer"},
                                "name": {"type": "string"},
                                "place_type": {
                                    "type": "string",
                                    "enum": ["관광지", "식당", "지역", "숙소", "교통", "기타"],
                                },
                                "visit_time": {"type": "string"},
                                "duration_minutes": {"type": "integer"},
                                "notes": {"type": "string"},
                                "needs_confirmation": {"type": "boolean"},
                            },
                            "required": [
                                "order",
                                "name",
                                "place_type",
                                "visit_time",
                                "duration_minutes",
                                "notes",
                                "needs_confirmation",
                            ],
                        },
                    },
                },
                "required": ["day_number", "date", "area", "places"],
            },
        },
        "unresolved_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["trip_title", "destination", "days", "unresolved_questions"],
}


def main() -> int:
    load_dotenv(ROOT / ".env")

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

    if not api_key:
        print("설정 오류: .env에 GEMINI_API_KEY를 설정하세요.")
        return 1

    if not INPUT_PATH.exists():
        print(f"입력 파일을 찾지 못했습니다: {INPUT_PATH}")
        print("먼저 .venv\\Scripts\\python.exe main.py 를 실행하세요.")
        return 1

    itinerary_text = INPUT_PATH.read_text(encoding="utf-8-sig").strip()
    if not itinerary_text:
        print("입력 텍스트가 비어 있습니다: output\\itinerary_text.txt")
        print("Notion 페이지 본문을 확인하고 main.py를 다시 실행하세요.")
        return 1

    prompt = f"""너는 여행 계획을 구조화하는 도우미다. 아래 원문에 적힌 정보만 사용해 한국어 JSON 데이터를 작성한다.

규칙:
- 원문에 등장하는 날짜별 일정을 분리하고, 장소의 방문 순서를 원문대로 유지한다.
- 날짜가 명시되지 않았다면 date는 빈 문자열로 둔다. 날짜를 추측하지 않는다.
- 방문 시간이 없으면 visit_time을 빈 문자열로 둔다.
- 체류 시간이 없으면 duration_minutes를 0으로 둔다.
- 정확한 식당이나 장소가 정해지지 않은 일반 지역(예: '도톤보리에서 점심')은 특정 가게를 지어내지 않는다.
- 이름이나 위치가 모호하거나 사용자가 선택해야 할 부분은 needs_confirmation을 true로 표시하고 unresolved_questions에 짧게 적는다.
- 좌표, 이동 거리, 이동 시간, 실제 영업시간은 만들어내지 않는다.
- 장소가 하나도 없다고 판단되면 억지로 만들지 말고 unresolved_questions에 이유를 적는다.
- 모든 문자열은 한국어로 작성한다. 장소의 고유명사는 원문 표기를 최대한 유지한다.

여행 계획 원문:
---
{itinerary_text}
---"""

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": SCHEMA,
                "temperature": 0.1,
            },
        )

        response_text = (response.text or "").strip()
        if not response_text:
            print("Gemini에서 비어 있는 응답을 받았습니다. 모델 이름과 API 사용량을 확인하세요.")
            return 1

        data = json.loads(response_text)
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    except json.JSONDecodeError as exc:
        print(f"JSON 해석 오류: {exc}")
        print("Gemini 응답을 JSON으로 해석하지 못했습니다. 다시 실행해 보세요.")
        return 1
    except Exception as exc:
        print(f"Gemini 분석 실패: {type(exc).__name__}: {exc}")
        print("API 키, 모델 이름, 네트워크 및 Gemini API 사용량을 확인하세요.")
        return 1

    days = data.get("days", [])
    place_count = sum(len(day.get("places", [])) for day in days)
    print("Gemini 일정 분석 성공")
    print(f"모델: {model}")
    print(f"여행 제목: {data.get('trip_title', '')}")
    print(f"날짜/일정 그룹: {len(days)}개")
    print(f"장소: {place_count}개")
    print(f"확인할 질문: {len(data.get('unresolved_questions', []))}개")
    print(f"JSON 저장: {OUTPUT_PATH}")

    for day in days:
        names = [place.get("name", "") for place in day.get("places", [])]
        print(f"  {day.get('day_number', '?')}일 차: " + (" → ".join(names) if names else "장소 없음"))

    if data.get("unresolved_questions"):
        print("추가 확인이 필요한 항목:")
        for question in data["unresolved_questions"]:
            print(f"  - {question}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
