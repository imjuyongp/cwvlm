"""VLM 방향별 판단 결과(JSONL)를 스팟 단위로 집계해 원본 CSV 에 병합한다.

원본 CSV 의 컬럼과 행 순서를 그대로 유지하고 결과 컬럼만 덧붙인다.
마지막에 전체 건수·판정별 건수와 함께 '확인 필요'/'사진 확인 불가' 지점 ID 를
따로 출력한다.

사용법:
    python vlm_merge.py
    python vlm_merge.py --results data/vlm_results.jsonl \
        --src data/streetview_spots_checked.csv \
        --out data/streetview_spots_screened.csv
"""

import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path

from vlm_prompt import CSV_COLUMN_NAMES

HEADINGS = (0, 90, 180, 270)
NO_PHOTO = "사진 확인 불가"
CANDIDATE, EXCLUDE, REVIEW = "도로 후보", "제외", "확인 필요"
CONF_ORDER = {"낮음": 0, "보통": 1, "높음": 2}

# 집계 결과로 덧붙일 컬럼 (한글 컬럼명은 vlm_prompt.CSV_COLUMN_NAMES 기준)
EXTRA_COLS = [
    CSV_COLUMN_NAMES["road_candidate"],          # 판정
    CSV_COLUMN_NAMES["road_candidate_type"],     # 세부 유형
    CSV_COLUMN_NAMES["evidence_road_candidate"], # 사진에서 확인한 근거
    CSV_COLUMN_NAMES["confidence"],              # 확신도
    CSV_COLUMN_NAMES["needs_review_reason"],     # 추가 확인이 필요한 이유
    "방향별_판정",
    "crosswalk", "median_barrier",
    "lane_clarity_median", "lane_clarity_min",
    "ped_sep_median", "ped_sep_min",
    "n_assessable",
]


def load_results(path: str) -> dict[str, dict]:
    """JSONL 을 읽어 pano_id -> 집계 결과 로 돌려준다."""
    by_pano: dict[str, list[dict]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            by_pano.setdefault(r["pano_id"], []).append(r)
    return {p: aggregate(recs) for p, recs in by_pano.items()}


def decide_candidate(votes: list[str], n: dict[str, int]) -> tuple[str, str]:
    """방향별 판정을 스팟 단위 하나로 합친다. (판정, 충돌 사유) 를 돌려준다.

    촬영 지점은 하나이므로, 한 방향이라도 도로임을 분명히 보여주면 도로 후보로
    본다. 다만 도로 후보가 1개뿐이고 제외가 섞여 있으면 판정이 갈린 것이므로
    자동 확정하지 않고 확인 필요로 넘긴다.
    """
    if n[CANDIDATE] >= 2:
        return CANDIDATE, ""
    if n[CANDIDATE] == 1 and n[EXCLUDE] == 0:
        return CANDIDATE, ""
    if n[CANDIDATE] == 1 and n[EXCLUDE] >= 1:
        return REVIEW, (f"방향별 판정이 갈림(도로 후보 {n[CANDIDATE]} / "
                        f"제외 {n[EXCLUDE]}). 촬영 지점이 도로인지 사람 확인 필요.")
    if n[REVIEW] >= 1:
        return REVIEW, ""
    if n[EXCLUDE] >= 1:
        return EXCLUDE, ""
    return NO_PHOTO, ""


def aggregate(records: list[dict]) -> dict:
    """한 pano 의 방향별 결과를 스팟 단위 값으로 집계한다."""
    by_heading = {r["heading"]: r for r in records}

    votes, per_dir = [], []
    for h in HEADINGS:
        r = by_heading.get(h)
        # 파일 누락·호출 실패는 사진 확인 불가로 처리한다
        v = NO_PHOTO if (r is None or "error" in r) else r.get("road_candidate", NO_PHOTO)
        votes.append(v)
        per_dir.append(f"{h}:{v}")

    n = Counter(votes)
    verdict, conflict = decide_candidate(votes, n)

    # 최종 판정에 기여한 방향들만 근거·유형·확신도의 근거로 삼는다
    contrib = [by_heading[h] for h, v in zip(HEADINGS, votes)
               if v == verdict and h in by_heading and "error" not in by_heading[h]]

    types = [c.get("road_candidate_type", "") for c in contrib if c.get("road_candidate_type")]
    detail = Counter(types).most_common(1)[0][0] if types else ""

    evidence = " | ".join(
        f"{c['heading']}°: {c.get('evidence_road_candidate', '')}"
        for c in contrib if c.get("evidence_road_candidate")
    )

    confs = [c.get("confidence") for c in contrib if c.get("confidence") in CONF_ORDER]
    confidence = min(confs, key=lambda x: CONF_ORDER[x]) if confs else ""
    if conflict:
        confidence = "낮음"

    reasons = [c.get("needs_review_reason", "") for c in contrib if c.get("needs_review_reason")]
    if conflict:
        reasons.insert(0, conflict)

    # --- 도로 안전 피쳐: 노면이 보인 방향만 대상 ---
    ok = [r for r in records if "error" not in r and r.get("assessable")]
    lanes = [r["lane_marking_clarity"] for r in ok if r.get("lane_marking_clarity") is not None]
    peds = [r["pedestrian_separation"] for r in ok if r.get("pedestrian_separation") is not None]

    return {
        CSV_COLUMN_NAMES["road_candidate"]: verdict,
        CSV_COLUMN_NAMES["road_candidate_type"]: detail,
        CSV_COLUMN_NAMES["evidence_road_candidate"]: evidence,
        CSV_COLUMN_NAMES["confidence"]: confidence,
        CSV_COLUMN_NAMES["needs_review_reason"]: " / ".join(reasons),
        "방향별_판정": ", ".join(per_dir),
        # 한 방향이라도 보이면 있는 것으로 본다
        "crosswalk": "yes" if any(r.get("crosswalk") == "yes" for r in ok) else ("no" if ok else ""),
        "median_barrier": "yes" if any(r.get("median_barrier") == "yes" for r in ok) else ("no" if ok else ""),
        # 중앙값은 대표값, 최솟값은 가장 취약한 방향. 둘 다 남겨 분석 단계에서 고른다
        "lane_clarity_median": statistics.median_low(lanes) if lanes else "",
        "lane_clarity_min": min(lanes) if lanes else "",
        "ped_sep_median": statistics.median_low(peds) if peds else "",
        "ped_sep_min": min(peds) if peds else "",
        "n_assessable": len(ok),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="data/vlm_results.jsonl")
    ap.add_argument("--src", default="data/streetview_spots_checked.csv")
    ap.add_argument("--out", default="data/streetview_spots_screened.csv")
    ap.add_argument("--id-col", default="spot_id",
                    help="요약에서 지점을 가리킬 컬럼명")
    ap.add_argument("--key-col", default="pano_id",
                    help="결과 JSONL 과 원본 CSV 를 맞출 식별자 컬럼명")
    args = ap.parse_args()

    # 1. JSONL 을 pano_id 별로 모은다
    by_pano: dict[str, list[dict]] = {}
    with open(args.results, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            by_pano.setdefault(r["pano_id"], []).append(r)
    print(f"판단 결과: {sum(len(v) for v in by_pano.values())}장 / pano {len(by_pano)}건")

    agg = {p: aggregate(recs) for p, recs in by_pano.items()}

    # 2. 원본 CSV 에 병합 (컬럼·행 순서 유지)
    with open(args.src, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows = list(reader)

    for col in EXTRA_COLS:
        if col not in fields:
            fields.append(col)

    matched = 0
    for row in rows:
        result = agg.get(row.get(args.key_col, ""))
        if result:
            row.update(result)
            matched += 1
        else:
            for col in EXTRA_COLS:
                row.setdefault(col, "")

    out_path = Path(args.out)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    # 3. 요약
    verdict_col = CSV_COLUMN_NAMES["road_candidate"]
    judged = [r for r in rows if r.get(verdict_col)]
    counts = Counter(r[verdict_col] for r in judged)

    print(f"\n저장: {out_path}")
    print(f"\n{'=' * 46}\n요약\n{'=' * 46}")
    print(f"원본 전체 행      : {len(rows):>6}")
    print(f"판정된 행         : {len(judged):>6}")
    print(f"판정 없음(로드뷰 X): {len(rows) - len(judged):>6}")
    print("\n[판정별 건수]")
    for v in (CANDIDATE, REVIEW, EXCLUDE, NO_PHOTO):
        c = counts.get(v, 0)
        pct = c / len(judged) * 100 if judged else 0
        print(f"  {v:<12} {c:>6}건  ({pct:5.1f}%)")

    conf_col = CSV_COLUMN_NAMES["confidence"]
    cands = [r for r in judged if r[verdict_col] == CANDIDATE]
    if cands:
        print("\n[도로 후보의 확신도]")
        for k, c in Counter(r[conf_col] for r in cands).most_common():
            print(f"  {k or '(없음)':<6} {c:>6}건")

    for v in (REVIEW, NO_PHOTO):
        ids = [r[args.id_col] for r in judged if r[verdict_col] == v]
        print(f"\n[{v}] {len(ids)}건")
        if ids:
            for i in range(0, len(ids), 8):
                print("  " + ", ".join(ids[i:i + 8]))


if __name__ == "__main__":
    main()
