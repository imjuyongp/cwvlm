"""data/streetview_spots_checked.csv 에서 img_status 가 true 인 스팟의 이미지를
방위별(0/90/180/270)로 data/images/{pano_id}_{heading}.jpg 로 내려받는다.

주의: 이미지 요청은 건당 과금된다 (pano 당 4건). 이미 받은 파일은 건너뛴다.
여러 스팟이 같은 pano_id 를 공유하면 한 번만 받는다.

사용법:
    python -m cwvlm.collect.download_streetview
    python -m cwvlm.collect.download_streetview data/streetview_spots_checked.csv data/images
"""

import csv
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cwvlm.collect.image import download_streetview_image
from cwvlm.collect.metadata import get_api_key
from cwvlm.config import HEADINGS

DEFAULT_CSV = Path("data/streetview_spots_checked.csv")
DEFAULT_IMAGE_DIR = Path("data/images")
MAX_WORKERS = 5


def download_one(pano_id: str, heading: int, image_dir: Path, api_key: str) -> bool:
    """pano_id 의 heading 방향 이미지를 저장한다. 성공(또는 이미 존재)하면 True."""
    out_path = image_dir / f"{pano_id}_{heading}.jpg"
    if out_path.exists():
        return True
    try:
        download_streetview_image(pano_id, out_path, heading=heading, api_key=api_key)
        return True
    except Exception as e:
        print(f"  실패 {pano_id} heading={heading}: {e}")
        return False


def main(csv_path: Path, image_dir: Path) -> None:
    api_key = get_api_key()
    image_dir.mkdir(parents=True, exist_ok=True)

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    # 중복 pano_id 제거 (순서 유지)
    pano_ids = list(dict.fromkeys(
        r["pano_id"] for r in rows if r.get("img_status") == "true" and r.get("pano_id")
    ))
    jobs = [(p, h) for p in pano_ids for h in HEADINGS]
    print(f"고유 pano {len(pano_ids)}건 × {len(HEADINGS)}방향 = {len(jobs)}장 다운로드 시작...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(lambda j: download_one(j[0], j[1], image_dir, api_key), jobs))

    ok = sum(results)
    print(f"완료: 성공 {ok}장 / 실패 {len(jobs) - ok}장 → {image_dir}/")


if __name__ == "__main__":
    args = sys.argv[1:]
    csv_path = Path(args[0]) if len(args) > 0 else DEFAULT_CSV
    image_dir = Path(args[1]) if len(args) > 1 else DEFAULT_IMAGE_DIR
    main(csv_path, image_dir)
