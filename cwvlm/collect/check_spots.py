"""data/streetview_spots.csv 의 모든 지점에 대해 Street View 메타데이터를 조회하고,
img_status(true/false) / img_date(YYYY-MM) 컬럼을 추가한 새 CSV 를 생성한다.

사용법:
    python -m cwvlm.collect.check_spots
    python -m cwvlm.collect.check_spots data/streetview_spots.csv data/streetview_spots_checked.csv
"""

import csv
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cwvlm.collect.image import build_streetview_url
from cwvlm.collect.metadata import get_api_key, get_streetview_metadata
from cwvlm.config import HEADINGS

DEFAULT_INPUT = Path("data/streetview_spots.csv")
DEFAULT_OUTPUT = Path("data/streetview_spots_checked.csv")
MAX_WORKERS = 10
URL_COLUMNS = [f"img_url_{h}" for h in HEADINGS]


def check_row(row: dict, api_key: str) -> dict:
    """한 행의 latitude/longitude 로 메타데이터를 조회해 status, date 를 돌려준다."""
    try:
        meta = get_streetview_metadata(
            location=(row["latitude"], row["longitude"]),
            api_key=api_key,
            raise_on_error=False,
        )
        return {
            "status": meta.get("status", ""),
            "date": meta.get("date", ""),
            "pano_id": meta.get("pano_id", ""),
        }
    except Exception as e:  # 네트워크 오류 등
        return {"status": f"ERROR: {e}", "date": "", "pano_id": ""}


def main(input_path: Path, output_path: Path) -> None:
    api_key = get_api_key()

    # utf-8-sig: 원본 CSV 의 BOM 처리
    with input_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    print(f"{len(rows)}건 조회 시작...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(lambda r: check_row(r, api_key), rows))

    status_counts: dict[str, int] = {}
    for row, res in zip(rows, results):
        row["img_status"] = "true" if res["status"] == "OK" else "false"
        row["img_date"] = res["date"]
        row["pano_id"] = res["pano_id"]
        # 방위별(0/90/180/270) 키 포함 URL. CSV 는 .gitignore 로 git 에 올라가지 않는다.
        for heading, col in zip(HEADINGS, URL_COLUMNS):
            row[col] = (
                build_streetview_url(res["pano_id"], heading=heading, api_key=api_key)
                if res["pano_id"]
                else ""
            )
        status_counts[res["status"]] = status_counts.get(res["status"], 0) + 1

    # 이미 존재하는 컬럼은 중복 추가하지 않는다 (같은 파일에 덮어쓸 수 있도록)
    for col in ["img_status", "img_date", "pano_id"] + URL_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"저장 완료: {output_path}")
    print("status 집계:")
    for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"  {status}: {count}")


if __name__ == "__main__":
    args = sys.argv[1:]
    input_path = Path(args[0]) if len(args) > 0 else DEFAULT_INPUT
    output_path = Path(args[1]) if len(args) > 1 else DEFAULT_OUTPUT
    main(input_path, output_path)
