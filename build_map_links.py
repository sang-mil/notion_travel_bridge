from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent
INPUT_PATH = ROOT / "output" / "itinerary.json"
OUTPUT_DIR = ROOT / "output"
CSV_PATH = OUTPUT_DIR / "map_import.csv"
MD_PATH = OUTPUT_DIR / "google_maps_links.md"


def text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def join_query(*parts: object) -> str:
    result: list[str] = []
    for part in parts:
        item = text(part)
        if item and item not in result:
            result.append(item)
    return ", ".join(result)


def maps_search_url(query: str) -> str:
    return "https://www.google.com/maps/search/?" + urlencode({"api": "1", "query": query})


def maps_directions_url(origin: str, destination: str) -> str:
    return "https://www.google.com/maps/dir/?" + urlencode(
        {"api": "1", "origin": origin, "destination": destination}
    )


def main() -> int:
    if not INPUT_PATH.exists():
        print(f"입력 파일을 찾지 못했습니다: {INPUT_PATH}")
        print("먼저 main.py와 analyze_itinerary.py를 순서대로 실행하세요.")
        return 1

    try:
        data = json.loads(INPUT_PATH.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"JSON 읽기 오류: {exc}")
        return 1

    destination = text(data.get("destination"))
    trip_title = text(data.get("trip_title")) or "여행 계획"
    days = data.get("days", [])
    rows: list[dict[str, str]] = []
    markdown: list[str] = [f"# {trip_title} — Google 지도 링크", ""]
    place_total = 0
    unresolved_total = 0

    for day in days:
        day_number = text(day.get("day_number")) or "?"
        day_date = text(day.get("date"))
        area = text(day.get("area"))
        places = sorted(day.get("places", []), key=lambda p: int(p.get("order", 0) or 0))
        markdown.append(f"## {day_number}일 차" + (f" ({day_date})" if day_date else ""))
        if area:
            markdown.append(f"지역: {area}")
        markdown.append("")

        day_entries: list[dict[str, str]] = []
        for place in places:
            name = text(place.get("name"))
            if not name:
                continue
            order = text(place.get("order"))
            place_type = text(place.get("place_type"))
            visit_time = text(place.get("visit_time"))
            duration = text(place.get("duration_minutes"))
            notes = text(place.get("notes"))
            needs_confirmation = bool(place.get("needs_confirmation", False))
            map_query = join_query(name, area, destination)
            search_url = maps_search_url(map_query)
            entry = {
                "Day": day_number,
                "Date": day_date,
                "Area": area,
                "Order": order,
                "Place": name,
                "Map search query": map_query,
                "Type": place_type,
                "Visit time": visit_time,
                "Duration minutes": duration,
                "Notes": notes,
                "Needs confirmation": "YES" if needs_confirmation else "NO",
                "Google Maps search URL": search_url,
            }
            rows.append(entry)
            day_entries.append(entry)
            place_total += 1
            if needs_confirmation:
                unresolved_total += 1

            suffix = " ⚠️ 장소 확인 필요" if needs_confirmation else ""
            markdown.append(f"{order or '?'}. **{name}**{suffix}")
            markdown.append(f"   - [Google 지도에서 장소 찾기]({search_url})")
            if visit_time:
                markdown.append(f"   - 방문 시간: {visit_time}")
            if duration and duration != "0":
                markdown.append(f"   - 예상 체류 시간: {duration}분")
            if notes:
                markdown.append(f"   - 메모: {notes}")

        if len(day_entries) >= 2:
            markdown.append("")
            markdown.append("**방문 순서대로 길 찾기**")
            for current, following in zip(day_entries, day_entries[1:]):
                route_url = maps_directions_url(current["Map search query"], following["Map search query"])
                markdown.append(f"- {current['Place']} → {following['Place']}: [Google 지도 길 찾기]({route_url})")
        markdown.append("")

    if not rows:
        print("일정에서 장소를 찾지 못했습니다. output\\itinerary.json의 days/places 내용을 확인하세요.")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "Day", "Date", "Area", "Order", "Place", "Map search query", "Type",
        "Visit time", "Duration minutes", "Notes", "Needs confirmation", "Google Maps search URL",
    ]
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    MD_PATH.write_text("\n".join(markdown).rstrip() + "\n", encoding="utf-8")

    print("지도 링크 생성 성공")
    print(f"여행: {trip_title}")
    print(f"장소: {place_total}개")
    print(f"확인 필요: {unresolved_total}개")
    print(f"CSV (Google My Maps 가져오기용): {CSV_PATH}")
    print(f"Google 지도 링크 모음: {MD_PATH}")
    print("참고: 생성된 링크는 온라인 Google 지도를 엽니다. 오프라인 지도는 Google 지도 앱에서 지역을 별도로 다운로드해야 합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
