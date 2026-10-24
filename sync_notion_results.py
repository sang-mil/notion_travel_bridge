from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
MAP_CONFIG_PATH = OUTPUT_DIR / "mymaps_config.json"
ITINERARY_PATH = OUTPUT_DIR / "itinerary.json"
SYNC_CONFIG_PATH = OUTPUT_DIR / "notion_sync_config.json"
API_BASE = "https://api.notion.com/v1"
DEFAULT_VERSION = "2026-03-11"
TEMPLATE_TITLE = "✈️ 여행 계획 템플릿 (Notion Travel Bridge)"
MAP_SECTION_TITLE = "🗺️ 생성된 Google My Maps 지도"
TEMPLATE_SECTION_TITLE = "🧩 재사용할 여행 계획 템플릿"


class NotionSyncError(RuntimeError):
    pass


def normalize_page_id(value: str) -> str:
    matches = re.findall(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32}",
        value.strip(),
    )
    if not matches:
        raise NotionSyncError("NOTION_PAGE_ID에서 페이지 ID를 찾지 못했습니다. .env 값을 확인하세요.")
    raw = matches[-1].replace("-", "").lower()
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


def rich_text(content: str, url: str | None = None) -> dict[str, Any]:
    text: dict[str, Any] = {"content": content[:2000]}
    if url:
        text["link"] = {"url": url}
    return {"type": "text", "text": text}


def block(block_type: str, content: str, url: str | None = None) -> dict[str, Any]:
    return {"object": "block", "type": block_type, block_type: {"rich_text": [rich_text(content, url)]}}


def template_blocks() -> list[dict[str, Any]]:
    """A reusable Notion page body. Keep text compatible with the itinerary parser."""
    result = [
        block("quote", "사용법: 이 페이지를 복제한 뒤 [대괄호] 안내를 실제 여행 정보로 바꾸세요. 사용하지 않는 예시/빈 항목은 삭제하세요."),
        block("heading_2", "1. 여행 기본 정보"),
        block("bulleted_list_item", "여행 제목: [예: 오사카·교토 4박 5일]"),
        block("bulleted_list_item", "목적지: [국가, 도시, 주요 지역]"),
        block("bulleted_list_item", "여행 기간: [YYYY-MM-DD ~ YYYY-MM-DD]"),
        block("bulleted_list_item", "동행자: [인원과 구성]"),
        block("bulleted_list_item", "여행 스타일: [관광/맛집/쇼핑/휴식 등 우선순위]"),
        block("bulleted_list_item", "이동·체력 조건: [예: 연속 도보 30분 이내, 계단 최소화, 1시간마다 휴식]"),
        block("bulleted_list_item", "예산·교통: [대략적인 예산, 대중교통/택시 선호]"),
        block("heading_2", "2. 날짜별 일정"),
        block("heading_3", "1일 차 — [YYYY-MM-DD]"),
        block("bulleted_list_item", "지역/숙소: [숙소나 시작 지역]"),
        block("bulleted_list_item", "방문 순서: [장소 A] → [장소 B] → [장소 C]"),
        block("bulleted_list_item", "꼭 가고 싶은 곳: [장소와 이유. 반드시 방문할 곳에는 ★ 표시]"),
        block("bulleted_list_item", "식사·휴식: [희망 식사, 휴식 시간, 휴식 장소]"),
        block("bulleted_list_item", "주의·대체안: [계단/언덕/긴 이동 회피, 비 오는 날 대안 등]"),
        block("heading_3", "2일 차 — [YYYY-MM-DD]"),
        block("bulleted_list_item", "지역/숙소: [숙소나 시작 지역]"),
        block("bulleted_list_item", "방문 순서: [장소 A] → [장소 B] → [장소 C]"),
        block("bulleted_list_item", "꼭 가고 싶은 곳: [장소와 이유. 반드시 방문할 곳에는 ★ 표시]"),
        block("bulleted_list_item", "식사·휴식: [희망 식사, 휴식 시간, 휴식 장소]"),
        block("bulleted_list_item", "주의·대체안: [피하고 싶은 이동, 대체 일정]"),
        block("heading_3", "3일 차 — [YYYY-MM-DD]"),
        block("bulleted_list_item", "지역/숙소: [숙소나 시작 지역]"),
        block("bulleted_list_item", "방문 순서: [장소 A] → [장소 B] → [장소 C]"),
        block("bulleted_list_item", "꼭 가고 싶은 곳: [장소와 이유. 반드시 방문할 곳에는 ★ 표시]"),
        block("bulleted_list_item", "식사·휴식: [희망 식사, 휴식 시간, 휴식 장소]"),
        block("bulleted_list_item", "주의·대체안: [피하고 싶은 이동, 대체 일정]"),
        block("heading_2", "3. 공통 조건과 미정 항목"),
        block("bulleted_list_item", "반드시 지킬 조건: [예: 하루 관광지 3곳 이하, 계단 최소화]"),
        block("bulleted_list_item", "미정/확인 필요: [예약, 운영일, 정확한 장소명 등]"),
        block("heading_2", "4. 지도 결과"),
        block("paragraph", "지도 링크는 자동화 실행 후 이 여행 계획 페이지에 기록됩니다. 생성된 핀을 눌러 장소가 맞는지 확인하세요."),
    ]
    return result


class NotionAPI:
    def __init__(self, token: str, version: str) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Notion-Version": version,
            "Content-Type": "application/json",
        })

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None,
                params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self.session.request(
                method, f"{API_BASE}{path}", json=body, params=params, timeout=30
            )
        except requests.RequestException as exc:
            raise NotionSyncError(f"Notion API에 연결하지 못했습니다: {exc}") from exc
        if not response.ok:
            try:
                payload = response.json()
                detail = payload.get("message", response.text[:500])
                code = payload.get("code", "unknown_error")
            except ValueError:
                detail, code = response.text[:500], "unknown_error"
            hint = ""
            if response.status_code == 401:
                hint = " .env의 NOTION_TOKEN을 확인하세요."
            elif response.status_code == 403:
                hint = " Notion 통합에 콘텐츠 삽입/수정 권한을 부여하고 대상 페이지를 해당 통합과 공유했는지 확인하세요."
            elif response.status_code == 404:
                hint = " 페이지 ID가 맞는지, 대상 페이지를 통합과 공유했는지 확인하세요."
            elif response.status_code == 429:
                hint = " Notion API 요청 제한입니다. 잠시 후 다시 실행하세요."
            raise NotionSyncError(
                f"Notion API 오류 ({response.status_code}, {code}): {detail}.{hint}"
            )
        try:
            return response.json() if response.content else {}
        except ValueError as exc:
            raise NotionSyncError("Notion API 응답을 JSON으로 읽지 못했습니다.") from exc

    def page(self, page_id: str) -> dict[str, Any]:
        return self.request("GET", f"/pages/{page_id}")

    def children(self, block_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            payload = self.request("GET", f"/blocks/{block_id}/children", params=params)
            result.extend(payload.get("results", []))
            if not payload.get("has_more"):
                return result
            cursor = payload.get("next_cursor")
            if not cursor:
                return result

    def append_children(self, block_id: str, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for start in range(0, len(children), 100):
            response = self.request(
                "PATCH", f"/blocks/{block_id}/children",
                body={"children": children[start:start + 100]},
            )
            results.extend(response.get("results", []))
        return results

    def update_text_block(self, block_id: str, content: str, url: str | None = None) -> None:
        self.request("PATCH", f"/blocks/{block_id}", body={
            "paragraph": {"rich_text": [rich_text(content, url)]}
        })

    def create_template_page(self, parent_page_id: str) -> tuple[str, str, bool]:
        for item in self.children(parent_page_id):
            if item.get("type") == "child_page":
                title = str(item.get("child_page", {}).get("title", "")).strip()
                if title == TEMPLATE_TITLE:
                    page_id = str(item.get("id", ""))
                    page = self.page(page_id)
                    if not self.children(page_id):
                        self.append_children(page_id, template_blocks())
                    return page_id, str(page.get("url", "")), False

        created = self.request("POST", "/pages", body={
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "properties": {
                "title": {
                    "title": [rich_text(TEMPLATE_TITLE)]
                }
            },
            "children": template_blocks(),
        })
        page_id = str(created.get("id", ""))
        page_url = str(created.get("url", ""))
        if not page_id:
            raise NotionSyncError("템플릿 페이지 생성 응답에 페이지 ID가 없습니다.")
        return page_id, page_url, True


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise NotionSyncError(f"필요한 파일을 찾을 수 없습니다: {path}\n먼저 run_all.py를 실행해 My Maps 지도를 생성하세요.")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise NotionSyncError(f"JSON 파일 형식이 잘못되었습니다: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise NotionSyncError(f"JSON 최상위 값은 객체여야 합니다: {path}")
    return data


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def get_block_rich_text(block_data: dict[str, Any]) -> list[dict[str, Any]]:
    block_type = block_data.get("type")
    value = block_data.get(block_type, {})
    rich = value.get("rich_text", []) if isinstance(value, dict) else []
    return rich if isinstance(rich, list) else []


def find_link_block(children: list[dict[str, Any]], url: str) -> str | None:
    for item in children:
        for fragment in get_block_rich_text(item):
            text_obj = fragment.get("text", {})
            link_obj = text_obj.get("link") if isinstance(text_obj, dict) else None
            if isinstance(link_obj, dict) and link_obj.get("url") == url:
                return str(item.get("id", "")) or None
    return None


def build_map_metadata(itinerary: dict[str, Any], map_url: str) -> str:
    title = str(itinerary.get("trip_title") or "여행 계획").strip()
    destination = str(itinerary.get("destination") or "미정").strip()
    days = itinerary.get("days", [])
    place_count = sum(len(d.get("places", [])) for d in days if isinstance(d, dict)) if isinstance(days, list) else 0
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    return f"여행: {title} | 목적지: {destination} | 장소 {place_count}개 | 마지막 동기화: {stamp}"


def sync() -> int:
    load_dotenv(ROOT / ".env")
    token = os.getenv("NOTION_TOKEN", "").strip()
    page_value = os.getenv("NOTION_PAGE_ID", "").strip()
    version = os.getenv("NOTION_VERSION", DEFAULT_VERSION).strip()
    if not token or not page_value:
        raise NotionSyncError(".env에 NOTION_TOKEN과 NOTION_PAGE_ID가 모두 설정되어 있어야 합니다.")
    parent_page_id = normalize_page_id(page_value)

    map_config = read_json(MAP_CONFIG_PATH)
    itinerary = read_json(ITINERARY_PATH)
    map_url = str(map_config.get("map_url") or "").strip()
    if not map_url.startswith("https://www.google.com/maps/d/"):
        raise NotionSyncError(
            "output\\mymaps_config.json에서 유효한 map_url을 찾지 못했습니다.\n"
            "지도 생성이 끝났는지 확인하세요. 현재 지도 URL이 있다면 해당 설정 파일을 확인해 주세요."
        )

    sync_config = {}
    if SYNC_CONFIG_PATH.exists():
        try:
            loaded = json.loads(SYNC_CONFIG_PATH.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                sync_config = loaded
        except json.JSONDecodeError:
            print("주의: notion_sync_config.json을 읽지 못해 설정을 새로 구성합니다.")

    client = NotionAPI(token, version)
    # Validate source page access before attempting a write.
    source_page = client.page(parent_page_id)
    source_url = str(source_page.get("url", ""))
    source_children = client.children(parent_page_id)

    template_page_id, template_url, created = client.create_template_page(parent_page_id)
    if not template_url:
        template_url = str(client.page(template_page_id).get("url", ""))
    if not template_url:
        raise NotionSyncError("템플릿 페이지가 생성됐지만 URL을 확인하지 못했습니다.")

    # The URL paragraph is updated in place on later runs rather than duplicated.
    map_block_id = str(sync_config.get("map_url_block_id", ""))
    map_meta_block_id = str(sync_config.get("map_meta_block_id", ""))
    map_title = "Google My Maps에서 여행 지도 열기"
    meta_text = build_map_metadata(itinerary, map_url)
    map_updated = False
    if map_block_id:
        try:
            client.update_text_block(map_block_id, map_title, map_url)
            map_updated = True
        except NotionSyncError as exc:
            if "(404," not in str(exc):
                raise
    if not map_updated:
        map_block_id = find_link_block(source_children, map_url) or ""
        if map_block_id:
            client.update_text_block(map_block_id, map_title, map_url)
            map_updated = True

    if not map_updated:
        created_blocks = client.append_children(parent_page_id, [
            block("heading_2", MAP_SECTION_TITLE),
            block("paragraph", map_title, map_url),
            block("paragraph", meta_text),
        ])
        if len(created_blocks) >= 3:
            map_block_id = str(created_blocks[1].get("id", ""))
            map_meta_block_id = str(created_blocks[2].get("id", ""))
    elif map_meta_block_id:
        try:
            client.update_text_block(map_meta_block_id, meta_text)
        except NotionSyncError as exc:
            if "(404," not in str(exc):
                raise
            map_meta_block_id = ""

    if not map_meta_block_id:
        # Use a separate metadata paragraph if the URL paragraph already existed without local sync state.
        refreshed = client.children(parent_page_id)
        found_map_id = map_block_id
        found_index = next((i for i, item in enumerate(refreshed) if item.get("id") == found_map_id), None)
        if found_index is not None and found_index + 1 < len(refreshed):
            following = refreshed[found_index + 1]
            if following.get("type") == "paragraph":
                map_meta_block_id = str(following.get("id", ""))
                client.update_text_block(map_meta_block_id, meta_text)
        if not map_meta_block_id:
            added = client.append_children(parent_page_id, [block("paragraph", meta_text)])
            if added:
                map_meta_block_id = str(added[0].get("id", ""))

    sync_config.update({
        "source_page_id": parent_page_id,
        "source_page_url": source_url,
        "map_url": map_url,
        "map_url_block_id": map_block_id,
        "map_meta_block_id": map_meta_block_id,
        "template_page_id": template_page_id,
        "template_page_url": template_url,
    })

    # Link the reusable template from the source page exactly once.
    refreshed_children = client.children(parent_page_id)
    template_link_block_id = str(sync_config.get("template_link_block_id", ""))
    if not template_link_block_id:
        template_link_block_id = find_link_block(refreshed_children, template_url) or ""
    if not template_link_block_id:
        appended = client.append_children(parent_page_id, [
            block("heading_2", TEMPLATE_SECTION_TITLE),
            block("paragraph", "템플릿 페이지 복제 후 내용과 날짜를 채워 새 여행 계획으로 사용하세요.", template_url),
        ])
        if len(appended) >= 2:
            template_link_block_id = str(appended[1].get("id", ""))
    sync_config["template_link_block_id"] = template_link_block_id
    sync_config["last_synced_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    save_json(SYNC_CONFIG_PATH, sync_config)

    print("\nNotion 동기화 완료")
    print(f"여행 지도: {map_url}")
    print(f"원본 Notion 페이지: {source_url or parent_page_id}")
    print(f"재사용 템플릿 {'생성' if created else '확인'}: {template_url}")
    print(f"동기화 설정 저장: {SYNC_CONFIG_PATH}")
    print("다음 실행부터는 지도 링크를 중복 추가하지 않고 기존 링크 블록을 갱신합니다.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="생성된 Google My Maps 링크와 여행 템플릿을 Notion에 기록합니다.")
    parser.add_argument("--dry-run", action="store_true", help="API를 호출하지 않고 입력 설정만 확인합니다.")
    args = parser.parse_args()
    try:
        load_dotenv(ROOT / ".env")
        if args.dry_run:
            page_value = os.getenv("NOTION_PAGE_ID", "").strip()
            if not os.getenv("NOTION_TOKEN", "").strip() or not page_value:
                raise NotionSyncError(".env에 NOTION_TOKEN과 NOTION_PAGE_ID를 설정하세요.")
            parent_id = normalize_page_id(page_value)
            map_config = read_json(MAP_CONFIG_PATH)
            itinerary = read_json(ITINERARY_PATH)
            print("검증 성공 (Notion API 호출 없음)")
            print(f"대상 페이지 ID: {parent_id}")
            print(f"지도 URL: {map_config.get('map_url', '(없음)')}")
            print(f"여행 제목: {itinerary.get('trip_title', '여행 계획')}")
            print(f"템플릿 제목: {TEMPLATE_TITLE}")
            return 0
        return sync()
    except NotionSyncError as exc:
        print(f"\nNotion 동기화 실패: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n사용자가 실행을 취소했습니다.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"\n예기치 않은 오류: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
