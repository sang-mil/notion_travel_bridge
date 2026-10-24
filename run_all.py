from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable

STAGES = [
    ("Notion에서 일정 가져오기", ROOT / "main.py"),
    ("Gemini로 일정 분석", ROOT / "analyze_itinerary.py"),
    ("지도용 CSV와 링크 생성", ROOT / "build_map_links.py"),
    ("Google My Maps 브라우저 자동화", ROOT / "publish_mymaps.py"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Notion 여행 계획부터 Google My Maps까지 한 번에 실행합니다.")
    parser.add_argument("--skip-notion", action="store_true", help="이미 생성된 itinerary_text.txt 사용")
    parser.add_argument("--skip-analysis", action="store_true", help="이미 생성된 itinerary.json 사용")
    parser.add_argument("--skip-links", action="store_true", help="이미 생성된 map_import.csv 사용")
    parser.add_argument("--new-map", action="store_true", help="항상 새 My Maps 지도를 생성")
    args, _unknown = parser.parse_known_args()

    skips = {
        "Notion에서 일정 가져오기": args.skip_notion,
        "Gemini로 일정 분석": args.skip_analysis,
        "지도용 CSV와 링크 생성": args.skip_links,
        "Google My Maps 브라우저 자동화": False,
    }
    for title, script in STAGES:
        if skips.get(title, False):
            print(f"\n[건너뜀] {title}")
            continue
        command = [PYTHON, str(script)]
        if title == "Google My Maps 브라우저 자동화" and args.new_map:
            command.append("--new-map")
        print(f"\n{'=' * 64}\n[단계] {title}\n{'=' * 64}", flush=True)
        result = subprocess.run(command, cwd=str(ROOT), check=False)
        if result.returncode != 0:
            print(f"\n중단: '{title}' 단계가 종료 코드 {result.returncode}를 반환했습니다.")
            print("위의 오류를 해결한 뒤 다시 실행하세요.")
            return result.returncode or 1
    print("\n전체 실행이 완료되었습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
