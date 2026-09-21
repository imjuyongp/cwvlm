"""Google Street View Static API - 이미지 요청 모듈.

문서: https://developers.google.com/maps/documentation/streetview/request-streetview?hl=ko

주의: 메타데이터와 달리 이미지 요청은 과금 대상이다.
"""

import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from streetview_metadata import get_api_key

IMAGE_URL = "https://maps.googleapis.com/maps/api/streetview"

# 360° 를 fov=90 으로 4등분한 촬영 방위 (북=0, 시계방향)
HEADINGS = (0, 90, 180, 270)


def build_streetview_url(
    pano_id: str,
    *,
    size: str = "640x640",
    heading: float | None = None,
    pitch: float = 0,
    fov: float = 90,
    api_key: str | None = None,
) -> str:
    """pano_id 로 Street View 이미지 URL 을 조립한다.

    Args:
        pano_id: 메타데이터 API 에서 얻은 파노라마 ID.
        size: "가로x세로" (최대 640x640).
        heading: 카메라 방위(0~360, 북=0). None 이면 파노라마 기본 방향.
        pitch: 상하 각도(-90~90). 기본 0.
        fov: 시야각(최대 120). 작을수록 줌인 효과. 기본 90.
        api_key: 포함할 API 키. None 이면 key 파라미터 없이 조립한다
            (저장/공유용. 실제 호출 시에는 &key=... 를 붙여야 한다).

    Returns:
        이미지 URL 문자열. <img src> 에 그대로 사용할 수 있다.
    """
    params: dict = {
        "pano": pano_id,
        "size": size,
        "pitch": pitch,
        "fov": fov,
    }
    if heading is not None:
        params["heading"] = heading
    if api_key:
        params["key"] = api_key
    return f"{IMAGE_URL}?{urllib.parse.urlencode(params)}"


def download_streetview_image(
    pano_id: str,
    out_path: str | Path,
    *,
    size: str = "640x640",
    heading: float | None = None,
    pitch: float = 0,
    fov: float = 90,
    api_key: str | None = None,
    timeout: float = 15.0,
) -> Path:
    """pano_id 로 Street View 이미지를 받아 파일로 저장한다.

    파라미터는 build_streetview_url 과 동일. 저장된 파일 경로를 반환한다.
    """
    url = build_streetview_url(
        pano_id,
        size=size,
        heading=heading,
        pitch=pitch,
        fov=fov,
        api_key=api_key or get_api_key(),
    )
    # 이미지가 없을 때 회색 플레이스홀더 대신 404 를 받도록
    url += "&return_error_code=true"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            content = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"요청 실패: {e.reason}") from e

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(content)
    return out_path


if __name__ == "__main__":
    # POINT000007 (streetview_spots_checked.csv 에서 조회한 pano_id)
    pano_id = "CAoSFkNJSE0wb2dLRUlDQWdJRHEzZmZhUlE."
    saved = download_streetview_image(pano_id, "data/images/POINT000007.jpg")
    print(f"저장 완료: {saved} ({saved.stat().st_size:,} bytes)")
