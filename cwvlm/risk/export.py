"""위험도 채점 결과를 원본 CSV 에 붙여 최종 산출물을 만든다.

원본 컬럼과 행 순서를 그대로 두고 점수 컬럼만 덧붙인다.
마지막에 우선도 분포와 상위 지점을 요약한다.

사용법:
    python -m cwvlm.risk.export
    python -m cwvlm.risk.export --results data/risk_scores.jsonl \
        --out data/최종_위험도_산정결과.csv
"""

import argparse
import collections
import csv
import json
from pathlib import Path

DOMAIN_NAMES = {
    "D1": "D1_보호수요", "D2": "D2_횡단위험",
    "D3": "D3_보행공간위험", "D4": "D4_운전자차량위험",
}
EXTRA = (list(DOMAIN_NAMES.values())
         + ["종합_환경위험", "예방적_현장점검_우선도", "자료_충분성",
            "점수_근거", "한계", "현장확인사항"])


def flatten(rec: dict) -> dict:
    out = {}
    ev, lim = [], []
    for key, name in DOMAIN_NAMES.items():
        d = rec.get(key) or {}
        out[name] = d.get("score", "")
        if d.get("evidence"):
            ev.append(f"[{key}] " + ", ".join(d["evidence"]))
        if d.get("limitation"):
            lim.append(f"[{key}] {d['limitation']}")
    out["종합_환경위험"] = (rec.get("environment_risk") or {}).get("score", "")
    out["예방적_현장점검_우선도"] = (rec.get("inspection_priority") or {}).get("score", "")
    out["자료_충분성"] = rec.get("data_sufficiency", "")
    out["점수_근거"] = " | ".join(ev)
    out["한계"] = " | ".join(lim)
    out["현장확인사항"] = " | ".join(rec.get("field_checks") or [])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="data/risk_scores.jsonl")
    ap.add_argument("--src", default="data/최종_데이터셋_VLM_공공데이터_out.csv")
    ap.add_argument("--out", default="data/최종_위험도_산정결과.csv")
    args = ap.parse_args()

    scored: dict[str, dict] = {}
    errors = 0
    with open(args.results, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("run", 1) != 1:      # 재현성 테스트용 반복분은 제외
                continue
            if "error" in r:
                errors += 1
            scored[r["spot_id"]] = r

    with open(args.src, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows = list(reader)

    fields += [c for c in EXTRA if c not in fields]
    matched = 0
    for row in rows:
        rec = scored.get(row["spot_id"])
        if rec:
            row.update(flatten(rec))
            matched += 1
        else:
            row.update({c: "" for c in EXTRA})

    out_path = Path(args.out)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"저장: {out_path}  ({len(rows)}행, 채점 {matched}행, 서술 실패 {errors}건)")

    done = [r for r in rows if r["예방적_현장점검_우선도"] != ""]
    if not done:
        return

    print(f"\n{'=' * 52}\n우선도 분포\n{'=' * 52}")
    c = collections.Counter(int(r["예방적_현장점검_우선도"]) for r in done)
    for lv in (100, 75, 50, 25, 0):
        n = c.get(lv, 0)
        bar = "█" * round(n / max(c.values()) * 30) if c else ""
        print(f"  {lv:>3}  {n:>4}곳 ({n / len(done) * 100:>5.1f}%)  {bar}")

    print(f"\n[도메인별 분포]")
    for name in DOMAIN_NAMES.values():
        cc = collections.Counter(int(r[name]) for r in done if r[name] != "")
        print(f"  {name:<18}" + "  ".join(f"{lv}:{cc.get(lv, 0):>3}" for lv in (0, 25, 50, 75, 100)))

    top = [r for r in done if int(r["예방적_현장점검_우선도"]) >= 75]
    print(f"\n[우선도 75 이상] {len(top)}곳")
    top.sort(key=lambda r: (-int(r["예방적_현장점검_우선도"]), -int(r["종합_환경위험"] or 0)))
    for r in top[:15]:
        print(f"  {r['spot_id']}  우선도 {r['예방적_현장점검_우선도']:>3} "
              f"(환경 {r['종합_환경위험']:>3} / D1 {r['D1_보호수요']:>3}) "
              f"{r.get('facility_name', '')[:20]}")
    if len(top) > 15:
        print(f"  ... 외 {len(top) - 15}곳")

    ins = collections.Counter(r["자료_충분성"] for r in done)
    print(f"\n[자료 충분성] " + " / ".join(f"{k} {v}곳" for k, v in ins.most_common()))


if __name__ == "__main__":
    main()
