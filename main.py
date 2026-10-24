from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
load_dotenv(BASE_DIR / ".env")

NOTION_API_BASE = "https://api.notion.com/v1"
DEFAULT_NOTION_VERSION = "2026-03-11"


class NotionBridgeError(RuntimeError):
    """Expected configuration or Notion API error."""


def normalize_page_id(value: str) -> str:
    """Accept a Notion page UUID or a full Notion page URL."""
    value = value.strip()
    matches = re.findall(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32}",
        value,
    )
    if not matches:
        raise NotionBridgeError(
            "NOTION_PAGE_ID에서 페이지 ID를 찾지 못했습니다. .env에 Notion 페이지 URL 또는 UUID를 넣어 주세요."
        )
    raw = matches[-1].replace("-", "").lower()
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


def rich_text_to_text(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        plain = item.get("plain_text")
        if isinstance(plain, str):
            parts.append(plain)
            continue
        text_obj = item.get("text")
        if isinstance(text_obj, dict) and isinstance(text_obj.get("content"), str):
            parts.append(text_obj["content"])
    return "".join(parts)


def extract_block_text(block: dict[str, Any]) -> str:
    block_type = block.get("type", "unknown")
    payload = block.get(block_type, {})
    if not isinstance(payload, dict):
        return ""

    if isinstance(payload.get("rich_text"), list):
        return rich_text_to_text(payload["rich_text"])
    if isinstance(payload.get("title"), list):
        return rich_text_to_text(payload["title"])
    if block_type == "child_page":
        return str(payload.get("title", ""))
    if block_type == "child_database":
        return str(payload.get("title", ""))
    if block_type == "table_row":
        cells = payload.get("cells", [])
        if isinstance(cells, list):
            return " | ".join(rich_text_to_text(cell) for cell in cells)
    if block_type in {"bookmark", "embed", "link_preview", "file", "pdf", "audio", "video"}:
        url = payload.get("url", "")
        caption = rich_text_to_text(payload.get("caption", []))
        if caption and url:
            return f"{caption} ({url})"
        return str(caption or url)
    if block_type == "equation":
        return str(payload.get("expression", ""))
    if block_type == "to_do":
        return rich_text_to_text(payload.get("rich_text", []))
    return rich_text_to_text(payload.get("caption", []))


def get_page_title(page: dict[str, Any]) -> str:
    properties = page.get("properties", {})
    if isinstance(properties, dict):
        for prop in properties.values():
            if isinstance(prop, dict) and prop.get("type") == "title":
                title = rich_text_to_text(prop.get("title", []))
                if title:
                    return title
    # Some page-like objects expose a direct title field.
    if isinstance(page.get("title"), list):
        return rich_text_to_text(page["title"])
    return "Notion 여행 계획"


class NotionClient:
    def __init__(self, token: str, version: str) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": version,
                "Content-Type": "application/json",
            }
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{NOTION_API_BASE}{path}"
        try:
            response = self.session.get(url, params=params, timeout=25)
        except requests.RequestException as exc:
            raise NotionBridgeError(f"Notion API에 연결하지 못했습니다: {exc}") from exc

        if not response.ok:
            try:
                body = response.json()
                detail = body.get("message", response.text[:500])
                code = body.get("code", "unknown_error")
            except ValueError:
                detail = response.text[:500]
                code = "unknown_error"

            if response.status_code == 401:
                hint = "토큰이 올바른지 .env의 NOTION_TOKEN을 확인하세요."
            elif response.status_code == 403:
                hint = "통합이 해당 페이지에 공유되어 있는지, 읽기 권한이 있는지 확인하세요."
            elif response.status_code == 404:
                hint = "페이지 ID가 맞는지, 페이지를 통합과 공유했는지 확인하세요."
            elif response.status_code == 429:
                hint = "요청 제한에 도달했습니다. 잠시 후 다시 시도하세요."
            else:
                hint = "오류 상세 내용을 확인하고 다시 시도하세요."
            raise NotionBridgeError(
                f"Notion API 오류 ({response.status_code}, {code}): {detail}\n해결 방법: {hint}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise NotionBridgeError("Notion API 응답을 JSON으로 읽지 못했습니다.") from exc

    def retrieve_page(self, page_id: str) -> dict[str, Any]:
        return self._get(f"/pages/{page_id}")

    def list_block_children(self, block_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self._get(f"/blocks/{block_id}/children", params=params)
            results.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return results

    def get_block_tree(self, parent_id: str, depth: int = 0, max_depth: int = 8) -> list[dict[str, Any]]:
        if depth > max_depth:
            return []
        tree: list[dict[str, Any]] = []
        for block in self.list_block_children(parent_id):
            block_type = block.get("type", "unknown")
            record: dict[str, Any] = {
                "id": block.get("id"),
                "type": block_type,
                "text": extract_block_text(block),
                "has_children": bool(block.get("has_children")),
            }
            if block_type == "to_do":
                record["checked"] = bool(block.get("to_do", {}).get("checked", False))
            if block.get("has_children"):
                record["children"] = self.get_block_tree(block["id"], depth + 1, max_depth)
            tree.append(record)
        return tree


def flatten_blocks(blocks: list[dict[str, Any]], depth: int = 0) -> list[str]:
    lines: list[str] = []
    for block in blocks:
        block_type = block.get("type", "unknown")
        text = str(block.get("text", "")).strip()
        prefix = "  " * depth
        if text:
            if block_type.startswith("heading_1"):
                line = f"# {text}"
            elif block_type.startswith("heading_2"):
                line = f"## {text}"
            elif block_type.startswith("heading_3"):
                line = f"### {text}"
            elif block_type == "bulleted_list_item":
                line = f"- {text}"
            elif block_type == "numbered_list_item":
                line = f"1. {text}"
            elif block_type == "to_do":
                line = f"[{ 'x' if block.get('checked') else ' '}] {text}"
            elif block_type == "quote":
                line = f"> {text}"
            else:
                line = text
            lines.append(prefix + line)
        children = block.get("children", [])
        if isinstance(children, list):
            lines.extend(flatten_blocks(children, depth + 1))
    return lines


def build_export(client: NotionClient, page_id: str) -> dict[str, Any]:
    page = client.retrieve_page(page_id)
    blocks = client.get_block_tree(page_id)
    title = get_page_title(page)
    text_lines = flatten_blocks(blocks)
    content_text = "\n".join(text_lines).strip()
    return {
        "source": {
            "provider": "Notion",
            "page_id": page_id,
            "page_title": title,
            "page_url": page.get("url", ""),
            "last_edited_time": page.get("last_edited_time", ""),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "notion_api_version": os.getenv("NOTION_VERSION", DEFAULT_NOTION_VERSION),
        },
        "content_text": content_text,
        "blocks": blocks,
    }


def save_export(data: dict[str, Any]) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "notion_input.json"
    text_path = OUTPUT_DIR / "itinerary_text.txt"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    title = data.get("source", {}).get("page_title", "Notion 여행 계획")
    url = data.get("source", {}).get("page_url", "")
    content = data.get("content_text", "")
    text_output = f"# {title}\n"
    if url:
        text_output += f"Notion 페이지: {url}\n"
    text_output += f"\n{content}\n"
    text_path.write_text(text_output, encoding="utf-8")
    return json_path, text_path


def load_config() -> tuple[str, str, str]:
    token = os.getenv("NOTION_TOKEN", "").strip()
    page_value = os.getenv("NOTION_PAGE_ID", "").strip()
    version = os.getenv("NOTION_VERSION", DEFAULT_NOTION_VERSION).strip()
    missing = []
    if not token:
        missing.append("NOTION_TOKEN")
    if not page_value:
        missing.append("NOTION_PAGE_ID")
    if missing:
        raise NotionBridgeError(
            f".env 설정이 누락되었습니다: {', '.join(missing)}\n"
            "프로젝트 폴더의 .env.example을 복사해 .env를 만들고 값을 입력하세요."
        )
    return token, normalize_page_id(page_value), version


def run_once(client: NotionClient, page_id: str) -> str:
    data = build_export(client, page_id)
    json_path, text_path = save_export(data)
    digest_source = json.dumps(
        {"title": data["source"]["page_title"], "content": data["content_text"]},
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    print("\nNotion → Python 연결 성공")
    print(f"페이지: {data['source']['page_title']}")
    print(f"가져온 텍스트 길이: {len(data['content_text'])}자")
    print(f"JSON 저장: {json_path}")
    print(f"텍스트 저장: {text_path}")
    if not data["content_text"]:
        print("주의: 페이지에서 읽을 텍스트 블록을 찾지 못했습니다. 페이지 본문과 공유 권한을 확인하세요.")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description="Notion 여행 계획을 Python으로 가져옵니다.")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Notion 페이지를 주기적으로 확인하고 내용이 바뀌면 다시 저장합니다.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=20,
        help="--watch 확인 주기(초). 기본값: 20초",
    )
    args = parser.parse_args()

    try:
        token, page_id, version = load_config()
        client = NotionClient(token, version)
        if not args.watch:
            run_once(client, page_id)
            return 0

        interval = max(10, args.interval)
        print(f"Notion 감시 모드 시작: {interval}초마다 확인합니다. 종료하려면 Ctrl+C를 누르세요.")
        previous_digest: str | None = None
        while True:
            try:
                data = build_export(client, page_id)
                digest_source = json.dumps(
                    {"title": data["source"]["page_title"], "content": data["content_text"]},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
                if digest != previous_digest:
                    json_path, text_path = save_export(data)
                    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{timestamp}] 변경 감지 — {data['source']['page_title']}")
                    print(f"  JSON: {json_path}")
                    print(f"  TXT : {text_path}")
                    previous_digest = digest
                else:
                    print("변경 없음")
            except (NotionBridgeError, requests.RequestException) as exc:
                print(f"확인 실패: {exc}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n감시 모드를 종료했습니다.")
        return 0
    except NotionBridgeError as exc:
        print(f"설정/연결 오류: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # Final safety net with a useful message rather than a raw stack trace.
        print(f"예기치 않은 오류: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
