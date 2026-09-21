"""data/streetview_spots_checked.csv 에서 img_status 가 true 인 스팟의 이미지를
data/images/{pano_id}.jpg 로 내려받고, img_file 컬럼에 저장 경로를 기록한다.

주의: 이미지 요청은 건당 과금된다. 이미 받은 파일은 건너뛴다.

사용법:
    python download_streetview_images.py
    python download_streetview_images.py data/streetview_spots_checked.csv data/images
"""

import csv
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from streetview_image import download_streetview_image
from streetview_metadata import get_api_key

DEFAULT_CSV = Path("data/streetview_spots_checked.csv")
DEFAULT_IMAGE_DIR = Path("data/images")
MAX_WORKERS = 5


def download_row(row: dict, image_dir: Path, api_key: str) -> str:
    """이미지를 받아 저장하고 파일 경로를 돌려준다. 실패하면 빈 문자열."""
    pano_id = row["pano_id"]
    out_path = image_dir / f"{pano_id}.jpg"
    if out_path.exists():
        return str(out_path)
    try:
        download_streetview_image(pano_id, out_path, api_key=api_key)
        return str(out_path)
    except Exception as e:
        print(f"  실패 {row['spot_id']} ({pano_id}): {e}")
        return ""


def main(csv_path: Path, image_dir: Path) -> None:
    api_key = get_api_key()
    image_dir.mkdir(parents=True, exist_ok=True)

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    targets = [r for r in rows if r.get("img_status") == "true" and r.get("pano_id")]
    print(f"대상 {len(targets)}건 다운로드 시작...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        paths = list(pool.map(lambda r: download_row(r, image_dir, api_key), targets))

    for row, path in zip(targets, paths):
        row["img_file"] = path
    for row in rows:
        row.setdefault("img_file", "")

    if "img_file" not in fieldnames:
        fieldnames.append("img_file")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    ok = sum(1 for p in paths if p)
    print(f"완료: 성공 {ok}건 / 실패 {len(targets) - ok}건")
    print(f"CSV 갱신: {csv_path}")


if __name__ == "__main__":
    args = sys.argv[1:]
    csv_path = Path(args[0]) if len(args) > 0 else DEFAULT_CSV
    image_dir = Path(args[1]) if len(args) > 1 else DEFAULT_IMAGE_DIR
    main(csv_path, image_dir)
