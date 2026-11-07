"""CSV 의 방향별 이미지 URL(Google Drive 등)에서 이미지를 내려받는다.

파일명은 {id}_{heading}.{확장자} 로, VLM 파이프라인이 그대로 읽을 수 있는 형태다.
이미 받은 파일은 건너뛰므로 중단 후 재개할 수 있다.

사용법:
    python -m cwvlm.collect.download_drive
    python -m cwvlm.collect.download_drive --src data/노인보호구역L.csv \
        --out-dir data/images/protection_zone --id-col spot_id
"""

import argparse
import csv
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from cwvlm.config import HEADINGS

MAX_WORKERS = 8
# content-type -> 확장자. 확장자를 응답에서 정하므로 PNG/JPEG 가 섞여도 된다.
EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg",
       "image/png": ".png", "image/webp": ".webp"}


def candidate_urls(url: str) -> list[str]:
    """Drive 링크는 export=view 가 HTML 안내 페이지를 돌려줄 때가 있어 대안을 함께 시도한다."""
    urls = [url]
    if "drive.google.com/uc" in url and "id=" in url:
        file_id = url.split("id=")[1].split("&")[0]
        urls += [
            f"https://drive.google.com/uc?export=download&id={file_id}",
            f"https://drive.usercontent.google.com/download?id={file_id}&export=view",
        ]
    return urls


def fetch(job: tuple[str, int, str], out_dir: Path, timeout: float) -> tuple[str, str]:
    """(id, heading, url) 하나를 받아 저장한다. (상태, 메시지) 를 돌려준다."""
    ident, heading, url = job
    existing = list(out_dir.glob(f"{ident}_{heading}.*"))
    if existing:
        return "skip", existing[0].name

    last = ""
    for candidate in candidate_urls(url):
        try:
            req = urllib.request.Request(candidate, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ctype = resp.headers.get("Content-Type", "").split(";")[0].strip()
                data = resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last = str(e)
            continue

        ext = EXT.get(ctype)
        if ext is None:
            last = f"이미지가 아님 (Content-Type={ctype})"
            continue

        (out_dir / f"{ident}_{heading}{ext}").write_bytes(data)
        return "ok", f"{ident}_{heading}{ext}"

    return "fail", f"{ident}_{heading}: {last}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/노인보호구역L.csv")
    ap.add_argument("--out-dir", default="data/images/protection_zone")
    ap.add_argument("--id-col", default="spot_id")
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.src, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    jobs = [(r[args.id_col], h, r[f"img_url_{h}"])
            for r in rows for h in HEADINGS if r.get(f"img_url_{h}")]
    print(f"{len(rows)}행 / 내려받을 이미지 {len(jobs)}장", flush=True)

    counts = {"ok": 0, "skip": 0, "fail": 0}
    fails: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, (status, msg) in enumerate(
                pool.map(lambda j: fetch(j, out_dir, args.timeout), jobs), 1):
            counts[status] += 1
            if status == "fail":
                fails.append(msg)
            if i % 40 == 0 or i == len(jobs):
                print(f"  [{i}/{len(jobs)}] 성공 {counts['ok']} / "
                      f"건너뜀 {counts['skip']} / 실패 {counts['fail']}", flush=True)

    total_mb = sum(p.stat().st_size for p in out_dir.iterdir()) / 1024 / 1024
    print(f"\n완료 → {out_dir}  ({len(list(out_dir.iterdir()))}장, {total_mb:.0f}MB)")
    if fails:
        print(f"\n실패 {len(fails)}건:")
        for m in fails[:20]:
            print(f"  {m}")


if __name__ == "__main__":
    main()
