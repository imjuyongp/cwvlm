"""라벨링용 표본 CSV 를 만든다.

로드뷰가 있는 스팟에서 pano 중복을 제거한 뒤 무작위 N개를 뽑고,
4방향 Street View 이미지 URL 과 빈 라벨 컬럼을 붙인다.
URL 에는 API 키가 포함되므로 생성된 CSV 를 외부에 공유하지 말 것
(data/*.csv 는 .gitignore 로 제외되어 있다).

사용법:
    python make_label_sample.py
    python make_label_sample.py --n 30 --seed 42
"""

import argparse
import csv
import random
from pathlib import Path

HEADINGS = (0, 90, 180, 270)
KEEP = ["spot_id", "facility_name", "address", "img_date", "pano_id"]
LABEL_COLS = ["crosswalk", "median_barrier", "guardrail",
              "lane_marking_clarity", "pedestrian_separation",
              "assessable", "hard", "note"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/streetview_spots_checked.csv")
    ap.add_argument("--out", default="data/label_sample_20.csv")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=20260926)
    args = ap.parse_args()

    with open(args.src, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("img_status") == "true"]

    # 같은 파노라마를 두 번 라벨링하지 않도록 pano_id 당 첫 행만 남긴다
    uniq: dict[str, dict] = {}
    for r in rows:
        uniq.setdefault(r["pano_id"], r)
    print(f"로드뷰 있는 행 {len(rows)} → 고유 pano {len(uniq)}")

    random.seed(args.seed)
    sample = random.sample(list(uniq.values()), min(args.n, len(uniq)))

    # 원본 CSV 의 방향별 URL 컬럼(키 포함)을 그대로 가져온다
    url_cols = [f"img_url_{h}" for h in HEADINGS]
    missing = 0
    out_path = Path(args.out)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=KEEP + url_cols + LABEL_COLS)
        writer.writeheader()
        for s in sample:
            row = {k: s[k] for k in KEEP}
            for col in url_cols:
                row[col] = s.get(col, "")
                if not row[col]:
                    missing += 1
            row.update({c: "" for c in LABEL_COLS})
            writer.writerow(row)

    print(f"생성: {out_path} ({len(sample)}건, URL 누락 {missing}개)")


if __name__ == "__main__":
    main()
