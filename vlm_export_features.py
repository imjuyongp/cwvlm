"""VLM 판단 결과를 스팟별 피쳐 값만 담은 CSV 로 내보낸다.

vlm_merge.py 가 원본 CSV 에 결과를 덧붙이는 것과 달리, 이쪽은 분석에 바로 쓸
피쳐 값만 추려 별도 파일로 만든다. 근거 문장은 길어서 기본으로 빼고,
--with-evidence 를 주면 포함한다.

사용법:
    python vlm_export_features.py
    python vlm_export_features.py --results data/vlm_changwon.jsonl \
        --src data/streetview_spots_checked.csv \
        --out data/changwon_features.csv --with-evidence
"""

import argparse
import csv
from collections import Counter
from pathlib import Path

from vlm_merge import CANDIDATE, EXCLUDE, NO_PHOTO, REVIEW, load_results
from vlm_prompt import CSV_COLUMN_NAMES

# 원본에서 그대로 가져올 식별·맥락 컬럼
KEEP = ["spot_id", "facility_name", "facility_types", "address",
        "latitude", "longitude", "protection_review", "img_date", "pano_id"]

FEATURE_COLS = [
    CSV_COLUMN_NAMES["road_candidate"],       # 판정
    CSV_COLUMN_NAMES["road_candidate_type"],  # 세부 유형
    CSV_COLUMN_NAMES["confidence"],           # 확신도
    "crosswalk", "median_barrier",
    "lane_clarity_median", "lane_clarity_min",
    "ped_sep_median", "ped_sep_min",
    "n_assessable", "방향별_판정",
]
EVIDENCE_COLS = [
    CSV_COLUMN_NAMES["evidence_road_candidate"],
    CSV_COLUMN_NAMES["needs_review_reason"],
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="data/vlm_changwon.jsonl")
    ap.add_argument("--src", default="data/streetview_spots_checked.csv")
    ap.add_argument("--out", default="data/changwon_features.csv")
    ap.add_argument("--with-evidence", action="store_true", help="근거 문장도 포함")
    ap.add_argument("--only-candidates", action="store_true",
                    help="판정이 '도로 후보'인 행만 내보낸다")
    args = ap.parse_args()

    agg = load_results(args.results)
    print(f"판단 완료 pano: {len(agg)}건")

    with open(args.src, encoding="utf-8-sig", newline="") as f:
        src_rows = list(csv.DictReader(f))

    cols = [c for c in KEEP if c in src_rows[0]] + FEATURE_COLS
    if args.with_evidence:
        cols += EVIDENCE_COLS

    verdict_col = CSV_COLUMN_NAMES["road_candidate"]
    out_rows = []
    for r in src_rows:
        result = agg.get(r.get("pano_id", ""))
        if not result:
            continue  # 로드뷰 없거나 아직 판단 전인 행은 제외
        if args.only_candidates and result[verdict_col] != CANDIDATE:
            continue
        row = {c: r.get(c, "") for c in KEEP if c in r}
        row.update({c: result.get(c, "") for c in cols if c in result})
        out_rows.append(row)

    out_path = Path(args.out)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)

    # ---- 요약 ----
    print(f"저장: {out_path}  ({len(out_rows)}행)")
    counts = Counter(r[verdict_col] for r in out_rows)
    print(f"\n[판정별]")
    for v in (CANDIDATE, REVIEW, EXCLUDE, NO_PHOTO):
        c = counts.get(v, 0)
        print(f"  {v:<12} {c:>5}건 ({c / len(out_rows) * 100:5.1f}%)" if out_rows else "")

    cands = [r for r in out_rows if r[verdict_col] == CANDIDATE]
    if not cands:
        return
    print(f"\n[도로 후보 {len(cands)}건의 피쳐 분포]")
    for feat in ("crosswalk", "median_barrier"):
        print(f"  {feat:<22}", dict(Counter(r[feat] for r in cands)))
    for feat in ("lane_clarity_median", "ped_sep_median"):
        vals = Counter(r[feat] for r in cands if r[feat] != "")
        print(f"  {feat:<22}", dict(sorted(vals.items())))

    types = Counter(r[CSV_COLUMN_NAMES["road_candidate_type"]] for r in cands)
    print(f"\n[도로 후보 세부 유형 상위 8]")
    for k, v in types.most_common(8):
        print(f"  {k:<24} {v:>4}건")


if __name__ == "__main__":
    main()
