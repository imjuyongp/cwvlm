"""231곳 지점에 대해 LLM 으로 사전 위험도를 채점한다.

이미지는 쓰지 않는다. 표 데이터만 읽는 순수 텍스트 추론 과제이므로
텍스트 전용 모델을 쓴다.

결과는 JSONL 로 남기고, 같은 (spot_id, run) 은 건너뛰므로 재개할 수 있다.
--runs 로 같은 지점을 여러 번 돌려 재현성을 측정할 수 있다.

사용법:
    python risk_score.py --limit 10 --runs 3        # 재현성 테스트 (순차)
    python risk_score.py                            # 231곳 본 실행
    python risk_score.py --backend openrouter --model <model>
"""

import argparse
import csv
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import risk_combine
import risk_domains
from risk_prompt import INPUT_COLUMNS, RESPONSE_SCHEMA, build_prompt

DEFAULT_SRC = Path("data/최종_데이터셋_VLM_공공데이터_out.csv")
DEFAULT_OUT = Path("data/risk_scores.jsonl")
DEFAULT_MODELS = {
    "ollama": "qwen3:14b",
    # thinking 없는 instruct 계열. 231건에 약 $0.11
    "openrouter": "qwen/qwen3-235b-a22b-2507",
}
# 프롬프트가 약 2,600 토큰이라 컨텍스트를 넉넉히 잡는다.
# qwen3 는 thinking 에 토큰을 많이 쓰므로 출력 상한도 여유 있게 둔다.
OLLAMA_OPTIONS = {"temperature": 0, "num_ctx": 8192, "num_predict": 4000}


class OllamaJudge:
    name = "ollama"

    def __init__(self, model: str, think: bool | None):
        import ollama

        self._ollama = ollama
        self.model = model
        self.think = think

    def __call__(self, prompt: str) -> dict:
        kwargs = {}
        if self.think is not None:
            kwargs["think"] = self.think
        resp = self._ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            format=RESPONSE_SCHEMA,
            options=OLLAMA_OPTIONS,
            **kwargs,
        )
        content = (resp["message"]["content"] or "").strip()
        if not content:
            raise RuntimeError(
                f"빈 응답 (done_reason={resp.get('done_reason')}, "
                f"eval={resp.get('eval_count')}, "
                f"thinking={len(resp['message'].get('thinking') or '')}자)"
            )
        return json.loads(content)


class OpenRouterJudge:
    name = "openrouter"

    def __init__(self, model: str, think: bool | None = None):
        from vlm_backend import OpenRouterBackend  # .env 로더와 클라이언트 재사용

        self.client = OpenRouterBackend(model).client
        self.model = model
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

    def __call__(self, prompt: str) -> dict:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": {
                "name": "risk_score", "strict": True, "schema": RESPONSE_SCHEMA}},
            temperature=0,
            max_tokens=1500,
        )
        if resp.usage:
            self.usage["prompt_tokens"] += resp.usage.prompt_tokens
            self.usage["completion_tokens"] += resp.usage.completion_tokens
            self.usage["calls"] += 1
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            raise RuntimeError(f"빈 응답 (finish_reason={resp.choices[0].finish_reason})")
        return json.loads(content)


def load_done(path: Path) -> set[tuple[str, int]]:
    done: set[tuple[str, int]] = set()
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    done.add((r["spot_id"], r.get("run", 1)))
                except (json.JSONDecodeError, KeyError):
                    continue
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--backend", default="ollama", choices=["ollama", "openrouter"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--runs", type=int, default=1,
                    help="같은 지점을 몇 번 돌릴지. 재현성 측정용")
    ap.add_argument("--limit", type=int, default=None, help="앞에서 N곳만 처리")
    ap.add_argument("--workers", type=int, default=1,
                    help="동시 요청 수. 재현성 측정 시에는 1 로 둘 것")
    ap.add_argument("--think", default="auto", choices=["auto", "on", "off"],
                    help="ollama 전용. thinking 모드 제어")
    args = ap.parse_args()

    model = args.model or DEFAULT_MODELS[args.backend]
    think = {"auto": None, "on": True, "off": False}[args.think]
    judge = (OllamaJudge(model, think) if args.backend == "ollama"
             else OpenRouterJudge(model))

    with open(args.src, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[:args.limit]

    missing = [c for c in INPUT_COLUMNS if c not in rows[0]]
    if missing:
        raise SystemExit(f"CSV 에 없는 입력 컬럼: {missing}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(out_path)

    jobs = [(r, run) for run in range(1, args.runs + 1)
            for r in rows if (r["spot_id"], run) not in done]
    print(f"백엔드: {judge.name} / {model}"
          + (f" (think={args.think})" if args.backend == "ollama" else ""))
    print(f"지점 {len(rows)}곳 × {args.runs}회 = {len(rows) * args.runs}건 "
          f"/ 처리할 건 {len(jobs)} (건너뜀 {len(rows) * args.runs - len(jobs)})",
          flush=True)
    if not jobs:
        return

    lock = threading.Lock()
    t0 = time.time()
    counter = {"n": 0, "fail": 0}

    def work(job):
        row, run = job
        # 점수는 전부 코드로 계산한다. 모델은 현장점검 항목 서술만 맡는다.
        result = risk_combine.apply(risk_domains.score_row(row))
        try:
            narrative = judge(build_prompt(row, result))
            result["field_checks"] = narrative.get("field_checks", [])
        except Exception as e:
            result["field_checks"] = []
            result["error"] = str(e)
        result["run"] = run
        result["model"] = model
        return result

    with out_path.open("a", encoding="utf-8") as f, \
            ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(work, jobs):
            with lock:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
                f.flush()
                counter["n"] += 1
                if "error" in result:
                    counter["fail"] += 1
                    print(f"  실패 {result['spot_id']} run{result['run']}: "
                          f"{result['error'][:80]}", flush=True)
                n = counter["n"]
                if n % 5 == 0 or n == len(jobs):
                    el = time.time() - t0
                    print(f"  [{n}/{len(jobs)}] {el:.0f}초 (건당 {el / n:.1f}초, "
                          f"남은 {(len(jobs) - n) * el / n / 60:.1f}분)", flush=True)

    el = time.time() - t0
    print(f"\n완료 → {out_path}")
    print(f"  {counter['n']}건 / 실패 {counter['fail']}건 / {el:.0f}초")
    usage = getattr(judge, "usage", None)
    if usage and usage["calls"]:
        print(f"  토큰: 입력 {usage['prompt_tokens']:,} / 출력 {usage['completion_tokens']:,}")


if __name__ == "__main__":
    main()
