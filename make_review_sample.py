"""'확인 필요' 로 분류된 지점만 뽑아 사람 검수용 CSV 를 만든다.

VLM 이 방향별로 판정이 갈려 자동 확정하지 못한 건들이다.
컬럼 구성은 원본 피쳐 CSV 와 동일하므로, 판정 컬럼만 고쳐서 그대로
되돌려 병합할 수 있다.

사용법:
    python make_review_sample.py
    python make_review_sample.py --verdict "사진 확인 불가" --out data/review_nophoto.csv
    python make_review_sample.py --with-urls          # 방향별 이미지 URL 을 덧붙인다
"""

import argparse
import csv
from pathlib import Path

from vlm_prompt import CSV_COLUMN_NAMES

HEADINGS = (0, 90, 180, 270)
VERDICT = CSV_COLUMN_NAMES["road_candidate"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/changwon_features.csv")
    ap.add_argument("--out", default="data/review_needed.csv")
    ap.add_argument("--verdict", default="확인 필요")
    ap.add_argument("--with-urls", action="store_true",
                    help="검수 편의를 위해 방향별 이미지 URL 컬럼을 끝에 덧붙인다")
    ap.add_argument("--urls-src", default="data/streetview_spots_checked.csv")
    args = ap.parse_args()

    with open(args.src, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows = [r for r in reader if r[VERDICT] == args.verdict]

    if args.with_urls:
        url_cols = [f"img_url_{h}" for h in HEADINGS]
        urls: dict[str, dict[str, str]] = {}
        with open(args.urls_src, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("pano_id"):
                    urls.setdefault(r["pano_id"], {c: r.get(c, "") for c in url_cols})
        for r in rows:
            r.update(urls.get(r["pano_id"], {c: "" for c in url_cols}))
        fields += [c for c in url_cols if c not in fields]

    out_path = Path(args.out)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"생성: {out_path}  ({len(rows)}행, 고유 pano "
          f"{len({r['pano_id'] for r in rows})}건)")
    print(f"컬럼 {len(fields)}개 — 원본 피쳐 CSV 와 동일"
          + (" + 이미지 URL 4개" if args.with_urls else ""))


if __name__ == "__main__":
    main()
