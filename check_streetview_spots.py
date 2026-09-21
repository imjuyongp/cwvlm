"""data/streetview_spots.csv 의 모든 지점에 대해 Street View 메타데이터를 조회하고,
img_status(true/false) / img_date(YYYY-MM) 컬럼을 추가한 새 CSV 를 생성한다.

사용법:
    python check_streetview_spots.py
    python check_streetview_spots.py data/streetview_spots.csv data/streetview_spots_checked.csv
"""

import csv
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from streetview_metadata import get_api_key, get_streetview_metadata

DEFAULT_INPUT = Path("data/streetview_spots.csv")
DEFAULT_OUTPUT = Path("data/streetview_spots_checked.csv")
MAX_WORKERS = 10


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
        status_counts[res["status"]] = status_counts.get(res["status"], 0) + 1

    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames + ["img_status", "img_date", "pano_id"]
        )
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
