"""같은 지점을 여러 번 채점한 결과로 재현성을 측정한다.

이 과제에는 정답셋이 없으므로 재현성이 사실상 유일한 객관적 선정 기준이다.
자기 자신과도 다른 답을 내는 모델은 정확도를 논할 수 없다.

사용법:
    python -m cwvlm.risk.consistency
    python -m cwvlm.risk.consistency --results data/risk_test_qwen3.jsonl
"""

import argparse
import collections
import json
from pathlib import Path

from cwvlm.risk import combine as risk_combine
from cwvlm.risk.prompt import SCORE_LEVELS

SCORE_FIELDS = ["D1", "D2", "D3", "D4"]          # 모델이 채점
COMPOSITE_FIELDS = ["environment_risk", "inspection_priority"]  # 코드가 계산


def get_score(rec: dict, field: str) -> int | None:
    v = rec.get(field)
    return v.get("score") if isinstance(v, dict) else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="data/risk_scores.jsonl")
    args = ap.parse_args()

    by_spot: dict[str, list[dict]] = collections.defaultdict(list)
    errors = 0
    with open(args.results, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if "error" in r:
                errors += 1
                continue
            by_spot[r["spot_id"]].append(r)

    repeated = {s: v for s, v in by_spot.items() if len(v) > 1}
    total = sum(len(v) for v in by_spot.values())
    model = next(iter(by_spot.values()))[0].get("model", "?") if by_spot else "?"

    print(f"모델: {model}")
    print(f"기록 {total + errors}건 (성공 {total} / 실패 {errors})")
    print(f"반복 측정된 지점: {len(repeated)}곳\n")
    if not repeated:
        print("반복 데이터가 없습니다. --runs 2 이상으로 실행하세요.")
        return

    # ---- 1. 점수 재현성 ----
    print("=" * 58)
    print("1. 재현성 — 같은 입력, 같은 점수가 나오는가")
    print("=" * 58)
    print(f"{'항목':<22}{'완전일치':>10}{'±5 이내':>10}{'최대편차':>10}")
    all_fields = SCORE_FIELDS + COMPOSITE_FIELDS
    worst = 0
    for field in all_fields:
        exact = near = 0
        spreads = []
        for recs in repeated.values():
            vals = [get_score(r, field) for r in recs]
            vals = [v for v in vals if v is not None]
            if len(vals) < 2:
                continue
            spread = max(vals) - min(vals)
            spreads.append(spread)
            exact += spread == 0
            near += spread <= 5
        n = len(spreads)
        if not n:
            continue
        worst = max(worst, max(spreads))
        print(f"{field:<22}{exact / n * 100:>9.0f}%{near / n * 100:>9.0f}%"
              f"{max(spreads):>10}")

    # ---- 2. 점수 분포 ----
    print("\n" + "=" * 58)
    print("2. 점수 분포 — 5단계를 고루 쓰는가")
    print("=" * 58)
    for field in SCORE_FIELDS:
        vals = [get_score(r, field) for recs in by_spot.values() for r in recs]
        vals = [v for v in vals if v is not None]
        c = collections.Counter(vals)
        print(f"  {field}  " + "  ".join(f"{lv}:{c.get(lv, 0):>3}" for lv in SCORE_LEVELS))
    flat = [get_score(r, f) for recs in by_spot.values() for r in recs
            for f in SCORE_FIELDS]
    flat = [v for v in flat if v is not None]
    off = [v for v in flat if v not in SCORE_LEVELS]
    print(f"\n  5단계 외 값: {len(off)}개" + (f" {off[:10]}" if off else ""))
    print(f"  50 비중    : {flat.count(50) / len(flat) * 100:.0f}%")

    # ---- 3. 종합 점수 규칙 준수 ----
    print("\n" + "=" * 58)
    print("3. 규칙 준수 — 종합 점수가 조합 규칙과 일치하는가")
    print("=" * 58)
    violations = []
    for recs in by_spot.values():
        for r in recs:
            g = lambda k: get_score(r, k)
            env = risk_combine.environment_risk(g("D2"), g("D3"), g("D4"))
            pri = risk_combine.inspection_priority(g("D1"), env)
            if g("environment_risk") != env or g("inspection_priority") != pri:
                violations.append((r["spot_id"], r.get("run"),
                                   g("environment_risk"), env,
                                   g("inspection_priority"), pri))
    checked = sum(len(v) for v in by_spot.values())
    print(f"검사 {checked}건 중 불일치 {len(violations)}건")
    for sid, run, e_got, e_exp, p_got, p_exp in violations[:10]:
        print(f"  {sid} run{run}: 환경 {e_got}(기대 {e_exp}) / 우선도 {p_got}(기대 {p_exp})")

    # ---- 4. 판정 ----
    print("\n" + "=" * 58)
    print("4. 판정")
    print("=" * 58)
    dom_worst = max((max(
        [get_score(r, f) for r in recs if get_score(r, f) is not None] or [0]
    ) - min(
        [get_score(r, f) for r in recs if get_score(r, f) is not None] or [0]
    )) for recs in repeated.values() for f in SCORE_FIELDS)
    print(f"  도메인 최대 편차 {dom_worst}점 (한 단계 = 25점)")
    print(f"  규칙 불일치 {len(violations)}건, 5단계 외 값 {len(off)}개, JSON 실패 {errors}건")
    if dom_worst == 0 and not violations and not off and not errors:
        print("  → 완전 재현. 231곳 본 실행 가능")
    elif dom_worst <= 25 and not violations and not off and not errors:
        print("  → 흔들림이 한 단계 이내. 본 실행 가능하나 인접 등급 차이는 유의하지 말 것")
    else:
        print("  → 두 단계 이상 흔들림. 프롬프트 보강 또는 모델 교체 필요")


if __name__ == "__main__":
    main()
