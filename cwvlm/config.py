"""패키지 전역 상수와 .env 로더."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 저장소 루트
# pano 당 촬영 방위. 360° 를 fov=90 으로 4등분 (북=0, 시계방향)
HEADINGS = (0, 90, 180, 270)


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """외부 라이브러리 없이 .env 파일의 KEY=VALUE 를 환경변수로 올린다."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
