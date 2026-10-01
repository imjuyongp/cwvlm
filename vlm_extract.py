"""이미지에서 도로 안전 피쳐를 추출한다.

방향(0/90/180/270)별로 1장씩 판단하고, 결과를 JSONL 로 저장한다.
집계(min/median)는 별도 단계에서 수행한다 — 원본 판단을 보존하기 위함.

사용법:
    python vlm_extract.py --sample 3                      # 무작위 3 pano
    python vlm_extract.py --panos <pano_id> [...]
    python vlm_extract.py --csv data/labels/sample_30.csv
    python vlm_extract.py --sample 3 --backend ollama     # 로컬 실행
"""

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from vlm_backend import make_backend

HEADINGS = (0, 90, 180, 270)
IMAGE_DIR = Path("data/images/train_spot")
OUT_PATH = Path("data/vlm_results.jsonl")


def run(pano_ids: list[str], image_dir: Path, out_path: Path,
        backend_kind: str, model: str | None, workers: int) -> None:
    backend = make_backend(backend_kind, model)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 이미 처리한 (pano_id, heading) 은 건너뛴다 — 중단 후 재개 가능
    done: set[tuple[str, int]] = set()
    if out_path.exists():
        with out_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    done.add((r["pano_id"], r["heading"]))
                except (json.JSONDecodeError, KeyError):
                    continue

    jobs = [(p, h) for p in pano_ids for h in HEADINGS if (p, h) not in done]
    print(f"백엔드: {backend.name} / {backend.model}")
    print(f"pano {len(pano_ids)}건 / 판단할 이미지 {len(jobs)}장 "
          f"(건너뜀 {len(pano_ids) * len(HEADINGS) - len(jobs)}장)", flush=True)
    if not jobs:
        return

    lock = threading.Lock()
    t0 = time.time()
    counter = {"n": 0, "fail": 0}

    def work(job: tuple[str, int]) -> dict:
        pano_id, heading = job
        # 확장자는 수집처에 따라 다르다 (Street View=jpg, 로드뷰 캡처=png)
        img = next(iter(sorted(image_dir.glob(f"{pano_id}_{heading}.*"))), None)
        if img is None:
            return {"pano_id": pano_id, "heading": heading, "error": "파일 없음"}
        try:
            result = backend.judge(img)
            result.update({"pano_id": pano_id, "heading": heading,
                           "model": backend.model})
        except Exception as e:
            result = {"pano_id": pano_id, "heading": heading,
                      "model": backend.model, "error": str(e)}
        return result

    with out_path.open("a", encoding="utf-8") as f, \
            ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(work, jobs):
            with lock:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
                f.flush()
                counter["n"] += 1
                if "error" in result:
                    counter["fail"] += 1
                    print(f"  실패 {result['pano_id'][:12]}.. h={result['heading']}: "
                          f"{result['error'][:70]}", flush=True)
                n = counter["n"]
                if n % 5 == 0 or n == len(jobs):
                    el = time.time() - t0
                    print(f"  [{n}/{len(jobs)}] {el:.0f}초 (장당 {el / n:.1f}초, "
                          f"남은 {(len(jobs) - n) * el / n / 60:.1f}분)", flush=True)

    el = time.time() - t0
    print(f"\n완료 → {out_path}")
    print(f"  {counter['n']}장 처리 / 실패 {counter['fail']}장 / {el:.0f}초")

    usage = getattr(backend, "usage", None)
    if usage and usage["calls"]:
        print(f"  토큰: 입력 {usage['prompt_tokens']:,} / "
              f"출력 {usage['completion_tokens']:,} "
              f"(호출당 입력 {usage['prompt_tokens'] // usage['calls']:,}, "
              f"출력 {usage['completion_tokens'] // usage['calls']:,})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panos", nargs="+", help="처리할 pano_id 목록")
    ap.add_argument("--sample", type=int, help="이미지 폴더에서 N개 pano 무작위 추출")
    ap.add_argument("--csv", help="식별자 컬럼이 있는 CSV 경로")
    ap.add_argument("--id-col", default="pano_id",
                    help="CSV 에서 식별자로 쓸 컬럼명. 이미지 파일명의 접두어가 된다")
    ap.add_argument("--image-dir", default=str(IMAGE_DIR))
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--backend", default="openrouter", choices=["openrouter", "ollama"])
    ap.add_argument("--model", default=None, help="백엔드 기본 모델 대신 사용할 모델명")
    ap.add_argument("--workers", type=int, default=6, help="동시 요청 수 (API 전용)")
    args = ap.parse_args()

    image_dir = Path(args.image_dir)

    if args.panos:
        pano_ids = args.panos
    elif args.csv:
        import csv
        with open(args.csv, encoding="utf-8-sig", newline="") as f:
            pano_ids = list(dict.fromkeys(
                r[args.id_col] for r in csv.DictReader(f) if r.get(args.id_col)
            ))
    elif args.sample:
        import random
        all_panos = sorted({p.name.rsplit("_", 1)[0] for p in image_dir.glob("*.jpg")})
        random.seed(42)
        pano_ids = random.sample(all_panos, min(args.sample, len(all_panos)))
    else:
        ap.error("--panos, --sample, --csv 중 하나가 필요합니다")

    workers = 1 if args.backend == "ollama" else args.workers
    run(pano_ids, image_dir, Path(args.out), args.backend, args.model, workers)


if __name__ == "__main__":
    main()
