from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Iterable

from playwright.sync_api import BrowserContext, Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
CSV_PATH = OUTPUT_DIR / "map_import.csv"
CONFIG_PATH = OUTPUT_DIR / "mymaps_config.json"
PROFILE_DIR = ROOT / ".mymaps_browser_profile"
SCREENSHOT_DIR = OUTPUT_DIR / "browser_debug"
MYMAPS_HOME = "https://www.google.com/mymaps"

CREATE_MAP_NAMES = [r"Create a new map", r"새 지도 만들기", r"지도 만들기"]
IMPORT_NAMES = [r"^Import$", r"^가져오기$"]
DEVICE_UPLOAD_NAMES = [
    r"Select a file from your device",
    r"기기에서 파일 선택",
    r"컴퓨터에서 파일 선택",
    r"파일 선택",
]
POSITION_COLUMN_NAMES = [r"^Map search query$", r"^Map search query\s*\(.*\)$"]
TITLE_COLUMN_NAMES = [r"^Place$"]
CONTINUE_NAMES = [r"^Continue$", r"^계속$", r"^다음$"]
FINISH_NAMES = [r"^Finish$", r"^완료$", r"^마침$"]


class AutomationError(RuntimeError):
    pass


def load_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return default or {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else (default or {})
    except (json.JSONDecodeError, OSError):
        return default or {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_csv(path: Path) -> int:
    if not path.exists():
        raise AutomationError(
            f"CSV 파일을 찾지 못했습니다: {path}\n"
            "먼저 analyze_itinerary.py와 build_map_links.py를 실행하세요."
        )
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        missing = [name for name in ("Place", "Map search query") if name not in headers]
        if missing:
            raise AutomationError("CSV에 필요한 열이 없습니다: " + ", ".join(missing))
        count = sum(1 for _ in reader)
    if count < 1:
        raise AutomationError("CSV에 가져올 장소가 없습니다.")
    if count > 2000:
        raise AutomationError(
            f"CSV에 {count}개 장소가 있습니다. Google My Maps는 2,000행 초과 가져오기를 지원하지 않으므로 나누어 가져오세요."
        )
    return count


def safe_screenshot(page: Page, tag: str) -> Path | None:
    try:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        output = SCREENSHOT_DIR / f"{stamp}-{tag}.png"
        page.screenshot(path=str(output), full_page=True, timeout=8000)
        return output
    except Exception:
        return None


def is_visible(locator: Locator) -> bool:
    try:
        return locator.count() > 0 and locator.first.is_visible(timeout=600)
    except Exception:
        return False


def click_first_visible(page: Page, patterns: Iterable[str], *, timeout: int = 2500) -> bool:
    """Try accessible controls first, then visible text. Names may be English or Korean."""
    for pattern in patterns:
        regex = re.compile(pattern, re.IGNORECASE)
        candidates = [
            page.get_by_role("button", name=regex),
            page.get_by_role("link", name=regex),
            page.get_by_role("menuitem", name=regex),
            page.get_by_text(regex),
        ]
        for candidate_group in candidates:
            try:
                count = min(candidate_group.count(), 8)
            except Exception:
                count = 0
            for index in range(count):
                candidate = candidate_group.nth(index)
                if not is_visible(candidate):
                    continue
                try:
                    candidate.click(timeout=timeout)
                    return True
                except Exception:
                    continue
    return False


def click_control_by_exact_name(page: Page, names: Iterable[str], timeout: int = 2500) -> bool:
    for name in names:
        regex = re.compile(name, re.IGNORECASE)
        for role in ("button", "link", "menuitem", "radio", "checkbox"):
            try:
                loc = page.get_by_role(role, name=regex)
                count = min(loc.count(), 8)
            except Exception:
                count = 0
            for index in range(count):
                item = loc.nth(index)
                if not is_visible(item):
                    continue
                try:
                    if role == "checkbox":
                        try:
                            if item.get_attribute("aria-checked") == "true" or item.is_checked():
                                return True
                        except Exception:
                            pass
                    item.click(timeout=timeout)
                    return True
                except Exception:
                    continue
        # Labels and custom UI elements frequently have no useful role.
        try:
            loc = page.get_by_text(regex)
            for index in range(min(loc.count(), 8)):
                item = loc.nth(index)
                if is_visible(item):
                    item.click(timeout=timeout)
                    return True
        except Exception:
            continue
    return False


def wait_for_manual_login(page: Page) -> None:
    """Require a pre-authenticated profile; never request Google login inside automation."""
    page.wait_for_timeout(1800)
    if "accounts.google.com" in page.url:
        raise AutomationError(
            "Google 로그인 화면으로 이동했습니다. Google은 자동화로 제어되는 브라우저에서의 로그인을 차단할 수 있습니다.\n"
            "자동화 브라우저에서 로그인하지 마세요. 프로젝트 폴더의 prepare_mymaps_login.ps1을 실행해 "
            "일반 Chrome 창에서 먼저 로그인한 뒤, 해당 창을 완전히 닫고 publish_mymaps.py를 다시 실행하세요."
        )

    sign_in_candidates = [
        page.get_by_role("button", name=re.compile(r"^Sign in$|^로그인$", re.IGNORECASE)),
        page.get_by_role("link", name=re.compile(r"^Sign in$|^로그인$", re.IGNORECASE)),
        page.get_by_text(re.compile(r"^Sign in$|^로그인$", re.IGNORECASE)),
    ]
    for candidate_group in sign_in_candidates:
        try:
            for index in range(min(candidate_group.count(), 5)):
                if is_visible(candidate_group.nth(index)):
                    raise AutomationError(
                        "이 전용 Chrome 프로필에서 Google 로그인 세션을 찾지 못했습니다.\n"
                        "자동화 브라우저 안에서 로그인하지 말고, prepare_mymaps_login.ps1을 실행해 "
                        "일반 Chrome 창에서 로그인한 뒤 창을 완전히 닫고 다시 시도하세요."
                    )
        except AutomationError:
            raise
        except Exception:
            continue


def prompt_for_manual_action(page: Page, message: str, screenshot_tag: str) -> None:
    screenshot = safe_screenshot(page, screenshot_tag)
    print("\n[자동화가 화면 요소를 찾지 못함]")
    print(message)
    if screenshot:
        print(f"현재 화면 스크린샷: {screenshot}")
    input("브라우저에서 해당 단계를 직접 완료한 다음 Enter를 누르세요... ")


def create_new_map(page: Page, context: BrowserContext) -> tuple[Page, str]:
    page.goto(MYMAPS_HOME, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500)
    wait_for_manual_login(page)

    clicked = click_first_visible(page, CREATE_MAP_NAMES, timeout=5000)
    if not clicked:
        prompt_for_manual_action(
            page,
            "My Maps 홈에서 '새 지도 만들기(Create a new map)'를 눌러 빈 지도를 만드세요.",
            "create-map",
        )

    # A new map may open in the same page or in a popup/tab.
    page.wait_for_timeout(3500)
    # Some My Maps home-page links open the map editor in a new tab.
    try:
        candidate_pages = list(context.pages)
        editor_pages = [candidate for candidate in candidate_pages if is_edit_map_url(candidate.url)]
        if editor_pages:
            page = editor_pages[-1]
    except Exception:
        pass
    if not is_edit_map_url(page.url):
        prompt_for_manual_action(
            page,
            "빈 지도를 여세요. 새 지도 편집 화면이 열린 것을 확인한 뒤 계속하세요.",
            "wait-map-editor",
        )

    if not is_edit_map_url(page.url):
        # Check if Google opened a link that changed URL only after interaction.
        try:
            page.wait_for_url(re.compile(r".*(maps/d/edit|mid=).*"), timeout=5000)
        except PlaywrightTimeoutError:
            raise AutomationError(
                f"새 지도 편집 URL을 확인할 수 없습니다. 현재 주소: {page.url}\n"
                "브라우저에서 지도를 만든 뒤 주소창 URL을 복사하고 다음 실행 때 --map-url로 전달하세요."
            )
    return page, page.url


def is_edit_map_url(url: str) -> bool:
    lowered = url.lower()
    return ("google.com/maps/d/" in lowered and "edit" in lowered) or ("mymaps.google.com" in lowered and "edit" in lowered) or ("mid=" in lowered and "maps" in lowered)


def use_file_input(page: Page, csv_path: Path) -> bool:
    inputs = page.locator('input[type="file"]')
    try:
        count = inputs.count()
    except Exception:
        count = 0
    # Hidden file inputs are supported by Playwright; use the last input because
    # some pages keep an unrelated Drive/photo input in the DOM.
    for index in reversed(range(count)):
        item = inputs.nth(index)
        try:
            item.set_input_files(str(csv_path), timeout=5000)
            return True
        except Exception:
            continue
    return False


def upload_csv(page: Page, csv_path: Path) -> None:
    # My Maps can show either a hidden input directly or a device-upload button.
    if use_file_input(page, csv_path):
        page.wait_for_timeout(2200)
        return

    clicked_device = click_first_visible(page, DEVICE_UPLOAD_NAMES, timeout=3000)
    if clicked_device and use_file_input(page, csv_path):
        page.wait_for_timeout(2200)
        return

    # Last resort: catch the native file chooser after selecting device upload.
    if clicked_device:
        try:
            with page.expect_file_chooser(timeout=5000) as chooser_info:
                click_first_visible(page, DEVICE_UPLOAD_NAMES, timeout=1500)
            chooser_info.value.set_files(str(csv_path))
            page.wait_for_timeout(2200)
            return
        except Exception:
            pass

    prompt_for_manual_action(
        page,
        f"CSV 파일을 선택해야 합니다. 브라우저에서 이 파일을 직접 선택하세요:\n{csv_path}",
        "choose-csv",
    )


def choose_column(page: Page, column_patterns: Iterable[str], stage_description: str, screenshot_tag: str) -> None:
    if click_control_by_exact_name(page, column_patterns, timeout=2500):
        return
    prompt_for_manual_action(
        page,
        f"'{stage_description}' 단계에서 지정 열을 자동으로 선택하지 못했습니다. 화면에서 해당 열을 선택하세요.",
        screenshot_tag,
    )


def import_new_layer(page: Page, csv_path: Path) -> None:
    if not click_first_visible(page, IMPORT_NAMES, timeout=4000):
        prompt_for_manual_action(
            page,
            "지도 왼쪽 레이어 패널의 '가져오기(Import)' 버튼을 눌러 새 레이어에 파일을 가져오는 창을 여세요.",
            "open-import",
        )
    upload_csv(page, csv_path)

    # If Google presents an intermediate Drive picker, local file upload can
    # expose Select/선택 before the column-selection wizard.
    page.wait_for_timeout(1000)
    current_text = safe_body_text(page)
    if any(word in current_text.lower() for word in ("choose a file", "파일 선택", "select a file")):
        if click_first_visible(page, [r"^Select$", r"^선택$"], timeout=1200):
            page.wait_for_timeout(1500)

    choose_column(page, POSITION_COLUMN_NAMES, "위치 지정 열: Map search query", "position-column")
    if not click_first_visible(page, CONTINUE_NAMES, timeout=3000):
        prompt_for_manual_action(
            page,
            "위치 지정 열을 선택한 뒤 '계속(Continue)'을 누르세요.",
            "continue-position",
        )
    page.wait_for_timeout(1000)

    choose_column(page, TITLE_COLUMN_NAMES, "핀 제목 열: Place", "title-column")
    if not click_first_visible(page, FINISH_NAMES, timeout=3000):
        prompt_for_manual_action(
            page,
            "핀 제목으로 Place를 선택한 뒤 '완료(Finish)'를 누르세요.",
            "finish-import",
        )
    page.wait_for_timeout(3500)


def safe_body_text(page: Page) -> str:
    try:
        return page.locator("body").inner_text(timeout=2000)
    except Exception:
        return ""


def replace_existing_layer(page: Page, csv_path: Path) -> None:
    """Best-effort reimport of the existing layer; fall back to guided manual steps."""
    opened = click_first_visible(
        page,
        [r"More options", r"More", r"Layer options", r"더보기", r"레이어 옵션", r"레이어 메뉴"],
        timeout=2000,
    )
    if not opened:
        prompt_for_manual_action(
            page,
            "기존 지도에서 대상 레이어의 더보기(⋮) 메뉴를 열고 '재가져오기 및 병합' 메뉴를 찾아 주세요.",
            "reimport-menu",
        )
    page.wait_for_timeout(400)

    if not click_first_visible(
        page,
        [r"Reimport and merge", r"재가져오기 및 병합"],
        timeout=2000,
    ):
        prompt_for_manual_action(
            page,
            "레이어 메뉴에서 'Reimport and merge / 재가져오기 및 병합'을 선택하세요.",
            "reimport-merge",
        )
    page.wait_for_timeout(500)

    if not click_first_visible(page, [r"Reimport", r"재가져오기"], timeout=1800):
        # Some UI versions show Replace all items directly under the merge menu.
        if not click_first_visible(page, [r"Replace all items", r"모든 항목 바꾸기", r"모든 항목 교체"], timeout=1200):
            prompt_for_manual_action(
                page,
                "재가져오기 하위 메뉴에서 'Reimport / 재가져오기'를 선택하세요.",
                "reimport-submenu",
            )
    page.wait_for_timeout(400)

    # Choose the destructive replacement option only; never append duplicates by default.
    if not click_first_visible(
        page,
        [r"Replace all items", r"모든 항목 바꾸기", r"모든 항목 교체"],
        timeout=2200,
    ):
        prompt_for_manual_action(
            page,
            "기존 장소 데이터를 새 CSV로 교체하려면 'Replace all items / 모든 항목 바꾸기'를 선택하세요.",
            "replace-items",
        )
    page.wait_for_timeout(700)
    upload_csv(page, csv_path)
    page.wait_for_timeout(1000)
    # Reimport/replace sometimes skips the column selector; handle it only when shown.
    text_now = safe_body_text(page)
    if "Map search query" in text_now or "위치 지정" in text_now or "placemarks" in text_now.lower():
        choose_column(page, POSITION_COLUMN_NAMES, "위치 지정 열: Map search query", "replace-position-column")
        if click_first_visible(page, CONTINUE_NAMES, timeout=1500):
            page.wait_for_timeout(700)
            choose_column(page, TITLE_COLUMN_NAMES, "핀 제목 열: Place", "replace-title-column")
            click_first_visible(page, FINISH_NAMES, timeout=1500)
    page.wait_for_timeout(3000)


def save_map_title_if_possible(page: Page, title: str) -> None:
    """Try rename map title; if the UI differs, leave Google default title unchanged."""
    if not title:
        return
    try:
        textboxes = page.get_by_role("textbox")
        count = textboxes.count()
        for index in range(min(count, 8)):
            box = textboxes.nth(index)
            if not box.is_visible(timeout=300):
                continue
            value = (box.input_value(timeout=500) or "").strip()
            if value.lower() in {"untitled map", "제목 없는 지도", "제목 없는 맵"}:
                box.fill(title[:100], timeout=1000)
                box.press("Enter", timeout=1000)
                page.wait_for_timeout(500)
                return
    except Exception:
        return


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Playwright로 Google My Maps에 여행 CSV를 가져옵니다. 첫 로그인은 브라우저에서 직접 완료합니다."
    )
    parser.add_argument("--map-url", help="저장된 지도 URL 대신 사용할 My Maps 편집 URL")
    parser.add_argument("--new-map", action="store_true", help="기존 지도 대신 새 지도를 만들어 CSV를 가져옵니다")
    parser.add_argument("--no-confirm", action="store_true", help="기존 레이어 교체 전 확인을 생략합니다")
    args = parser.parse_args()

    try:
        place_count = validate_csv(CSV_PATH)
    except AutomationError as exc:
        print(f"오류: {exc}")
        return 1

    config = load_json(CONFIG_PATH)
    saved_map_url = (args.map_url or ("" if args.new_map else config.get("map_url", ""))).strip()
    csv_hash = sha256_file(CSV_PATH)
    if saved_map_url and config.get("last_csv_sha256") == csv_hash and not args.new_map:
        print("이번 CSV는 마지막으로 가져온 파일과 동일합니다. 지도 업로드를 건너뜁니다.")
        print(f"지도: {saved_map_url}")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    print("Google My Maps 브라우저 자동화 시작")
    print(f"CSV: {CSV_PATH}")
    print(f"장소: {place_count}개")
    print("전용 브라우저 프로필을 사용합니다. 로그인은 브라우저 안에서 직접 완료하세요.")

    with sync_playwright() as playwright:
        try:
            context: BrowserContext = playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=False,
                chromium_sandbox=True,
                viewport={"width": 1440, "height": 960},
                accept_downloads=True,
                args=["--start-maximized"],
            )
        except Exception as chrome_exc:
            print("Google Chrome을 자동화 프로필로 실행하지 못했습니다.")
            print("자동화 프로필을 사용하는 Chrome 창이 이미 열려 있으면 먼저 완전히 닫으세요.")
            print("Playwright Chromium으로 자동 전환하지 않습니다. Google 로그인 세션은 Chrome 프로필에 저장되어야 합니다.")
            print(f"오류: {type(chrome_exc).__name__}: {chrome_exc}")
            return 1

        try:
            page = context.pages[0] if context.pages else context.new_page()
            map_title = ""
            itinerary_path = OUTPUT_DIR / "itinerary.json"
            if itinerary_path.exists():
                data = load_json(itinerary_path)
                map_title = str(data.get("trip_title", "")).strip()

            if saved_map_url and not args.new_map:
                page.goto(saved_map_url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                wait_for_manual_login(page)
                if not args.no_confirm:
                    print("\n기존 지도 레이어의 데이터를 최신 CSV로 교체합니다.")
                    print("기존 레이어 안의 장소 항목이 새 CSV 내용으로 바뀔 수 있습니다.")
                    answer = input("계속하려면 REPLACE 를 입력하세요: ").strip()
                    if answer != "REPLACE":
                        print("취소했습니다. 지도는 변경하지 않았습니다.")
                        return 0
                replace_existing_layer(page, CSV_PATH)
                final_map_url = saved_map_url
            else:
                page, final_map_url = create_new_map(page, context)
                save_map_title_if_possible(page, map_title)
                import_new_layer(page, CSV_PATH)
                final_map_url = page.url or final_map_url

            config.update(
                {
                    "map_url": final_map_url,
                    "map_title": map_title,
                    "csv_path": str(CSV_PATH),
                    "last_csv_sha256": csv_hash,
                    "last_imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "place_count": place_count,
                }
            )
            save_json(CONFIG_PATH, config)
            screenshot = safe_screenshot(page, "import-complete")
            print("\nMy Maps 가져오기 작업이 끝났습니다.")
            print(f"지도 URL: {final_map_url}")
            print(f"설정 저장: {CONFIG_PATH}")
            if screenshot:
                print(f"완료 화면 스크린샷: {screenshot}")
            print("브라우저 창에서 핀이 정상적으로 표시되는지 한 번 확인하세요.")
            return 0
        except AutomationError as exc:
            screenshot = safe_screenshot(page, "automation-error") if "page" in locals() else None
            print(f"자동화 오류: {exc}")
            if screenshot:
                print(f"화면 스크린샷: {screenshot}")
            return 1
        except Exception as exc:
            screenshot = safe_screenshot(page, "unexpected-error") if "page" in locals() else None
            print(f"예상하지 못한 오류: {type(exc).__name__}: {exc}")
            if screenshot:
                print(f"화면 스크린샷: {screenshot}")
            print("Google My Maps UI가 변경된 경우 스크린샷을 확인해 선택자를 조정해야 할 수 있습니다.")
            return 1
        finally:
            try:
                context.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
