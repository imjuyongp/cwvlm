"""VLM 결과를 사람 정답셋과 대조해 피쳐별 정확도를 계산한다.

정답셋은 스팟 단위, VLM 결과는 방향별이므로 vlm_merge.aggregate 로 먼저 집계한다.

채점 규칙
  - 판정(도로 후보 여부): 정답셋의 assessable 과 대조.
    정답 TRUE  ↔ 도로 후보
    정답 FALSE ↔ 제외
    VLM 이 '확인 필요'/'사진 확인 불가' 면 보류로 빼고 별도 집계한다.
  - 나머지 피쳐: 정답셋에 값이 있는 행만 대상. 사람이 판단 못 한 행은 제외.

사용법:
    python vlm_score.py
    python vlm_score.py --results data/vlm_labelset_20.jsonl \
        --truth "data/label_sample_20_정답셋.csv"
"""

import argparse
import csv
import json
from collections import Counter

from vlm_merge import CANDIDATE, EXCLUDE, NO_PHOTO, REVIEW, aggregate
from vlm_prompt import CSV_COLUMN_NAMES

BOOL_FEATURES = ["crosswalk", "median_barrier"]
SCORE_FEATURES = {
    "lane_marking_clarity": "lane_clarity_median",
    "pedestrian_separation": "ped_sep_median",
}


def cohen_kappa(pairs: list[tuple]) -> float | None:
    """관측 일치도에서 우연 일치를 뺀 값. 1.0 = 완전 일치, 0 = 우연 수준."""
    if not pairs:
        return None
    n = len(pairs)
    po = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return None if pe == 1 else (po - pe) / (1 - pe)


def quadratic_weighted_kappa(pairs: list[tuple[int, int]], k: int = 4) -> float | None:
    """순서 척도용. 3점을 0점으로 찍는 큰 오차에 더 큰 벌점을 준다."""
    if not pairs:
        return None
    n = len(pairs)
    o = [[0.0] * k for _ in range(k)]
    for a, b in pairs:
        o[a][b] += 1
    ha, hb = [0.0] * k, [0.0] * k
    for a, b in pairs:
        ha[a] += 1
        hb[b] += 1
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = (i - j) ** 2 / (k - 1) ** 2
            num += w * o[i][j]
            den += w * ha[i] * hb[j] / n
    return None if den == 0 else 1 - num / den


def fmt(v: float | None, pct: bool = False) -> str:
    if v is None:
        return "  n/a"
    return f"{v * 100:5.1f}%" if pct else f"{v:5.2f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="data/vlm_labelset_20.jsonl")
    ap.add_argument("--truth", default="data/label_sample_20_정답셋.csv")
    args = ap.parse_args()

    by_pano: dict[str, list[dict]] = {}
    with open(args.results, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                by_pano.setdefault(r["pano_id"], []).append(r)
    pred = {p: aggregate(recs) for p, recs in by_pano.items()}

    with open(args.truth, encoding="utf-8-sig", newline="") as f:
        truth = list(csv.DictReader(f))

    verdict_col = CSV_COLUMN_NAMES["road_candidate"]
    rows = [(t, pred[t["pano_id"]]) for t in truth if t["pano_id"] in pred]
    print(f"대조 대상: {len(rows)} / 정답셋 {len(truth)}건\n")

    # ---------------- 1. 판정 (도로 후보 여부) ----------------
    print("=" * 62)
    print("1. 판정 — 촬영 지점이 도로인가  (정답셋 assessable 과 대조)")
    print("=" * 62)

    want = {"TRUE": CANDIDATE, "FALSE": EXCLUDE}
    pairs, held, conf_mat = [], [], Counter()
    for t, p in rows:
        gt = t["assessable"].strip().upper()
        pv = p[verdict_col]
        conf_mat[(gt, pv)] += 1
        if pv in (REVIEW, NO_PHOTO):
            held.append((t["spot_id"], gt, pv))
        elif gt in want:
            pairs.append((want[gt], pv))

    print(f"{'정답셋':<8} {'VLM 판정':<14} 건수")
    for (gt, pv), c in sorted(conf_mat.items()):
        mark = "" if pv in (REVIEW, NO_PHOTO) else ("  ✓" if want.get(gt) == pv else "  ✗")
        print(f"{gt:<8} {pv:<14} {c:>3}{mark}")

    if pairs:
        acc = sum(1 for a, b in pairs if a == b) / len(pairs)
        print(f"\n채점 대상 {len(pairs)}건 (보류 {len(held)}건 제외)")
        print(f"  정확도 {fmt(acc, True)}   Cohen's κ {fmt(cohen_kappa(pairs))}")
    if held:
        print(f"\n  보류(확인 필요/사진 확인 불가) {len(held)}건:")
        for sid, gt, pv in held:
            print(f"    {sid}  정답={gt}  VLM={pv}")

    # ---------------- 2. 불린 피쳐 ----------------
    print("\n" + "=" * 62)
    print("2. 불린 피쳐  (정답셋에 값이 있는 행만)")
    print("=" * 62)
    print(f"{'피쳐':<18}{'n':>4}{'정확도':>9}{'κ':>8}   오답 스팟")
    for feat in BOOL_FEATURES:
        pr, wrong = [], []
        for t, p in rows:
            g, v = t.get(feat, "").strip(), p.get(feat, "")
            if g and v:
                pr.append((g, v))
                if g != v:
                    wrong.append(f"{t['spot_id']}({g}→{v})")
        acc = sum(1 for a, b in pr if a == b) / len(pr) if pr else None
        print(f"{feat:<18}{len(pr):>4}{fmt(acc, True):>9}{fmt(cohen_kappa(pr)):>8}   "
              f"{', '.join(wrong) if wrong else '-'}")

    # ---------------- 3. 점수 피쳐 ----------------
    print("\n" + "=" * 62)
    print("3. 점수 피쳐 (0~3)  — ±1 은 인접 오차 허용 기준")
    print("=" * 62)
    print(f"{'피쳐':<24}{'n':>4}{'정확일치':>9}{'±1 이내':>9}{'QWK':>8}")
    detail = []
    for gt_col, pred_col in SCORE_FEATURES.items():
        pr = []
        for t, p in rows:
            g, v = t.get(gt_col, "").strip(), p.get(pred_col, "")
            if g != "" and v != "":
                pr.append((int(g), int(v), t["spot_id"]))
        if not pr:
            print(f"{gt_col:<24}{0:>4}{'n/a':>9}{'n/a':>9}{'n/a':>8}")
            continue
        exact = sum(1 for a, b, _ in pr if a == b) / len(pr)
        near = sum(1 for a, b, _ in pr if abs(a - b) <= 1) / len(pr)
        qwk = quadratic_weighted_kappa([(a, b) for a, b, _ in pr])
        print(f"{gt_col:<24}{len(pr):>4}{fmt(exact, True):>9}{fmt(near, True):>9}{fmt(qwk):>8}")
        detail.append((gt_col, [(s, a, b) for a, b, s in pr if a != b]))

    for name, wrong in detail:
        if wrong:
            print(f"\n  [{name}] 불일치 {len(wrong)}건 (정답→VLM)")
            for sid, a, b in wrong:
                print(f"    {sid}  {a} → {b}" + ("   (2단계 이상)" if abs(a - b) >= 2 else ""))


if __name__ == "__main__":
    main()
