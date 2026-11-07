"""Google Street View Static API - Metadata 엔드포인트 호출 모듈.

문서: https://developers.google.com/maps/documentation/streetview/metadata?hl=ko

API 키는 환경변수 GOOGLE_MAPS_API_KEY 로 전달한다.
(프로젝트 루트의 .env 파일에 적어두면 자동으로 읽는다.)
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from cwvlm.config import load_dotenv

METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"


def get_api_key() -> str:
    load_dotenv()
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise RuntimeError(
            "GOOGLE_MAPS_API_KEY 환경변수가 설정되지 않았습니다. "
            ".env 파일 또는 환경변수로 API 키를 지정하세요."
        )
    return key


def get_streetview_metadata(
    location: str | tuple[float, float] | None = None,
    pano: str | None = None,
    *,
    radius: int = 50,
    source: str = "default",
    api_key: str | None = None,
    timeout: float = 10.0,
    raise_on_error: bool = True,
) -> dict:
    """Street View 파노라마 메타데이터를 조회한다.

    Args:
        location: "위도,경도" 문자열, (위도, 경도) 튜플, 또는 주소 문자열.
        pano: 파노라마 ID. location 대신 사용할 수 있다.
        radius: location 기준 검색 반경(미터). 기본 50.
        source: "default" 또는 "outdoor"(실외 파노라마만).
        api_key: 명시하지 않으면 환경변수에서 읽는다.
        timeout: 요청 타임아웃(초).
        raise_on_error: False 이면 status != "OK" 여도 예외 없이 응답 dict 를 그대로 반환한다.

    Returns:
        API 응답 JSON(dict). 정상이면 status == "OK" 이고
        pano_id, date, location{lat,lng}, copyright 등을 포함한다.

    Raises:
        ValueError: location/pano 둘 다 없거나 둘 다 있을 때.
        RuntimeError: HTTP 오류, 또는 raise_on_error=True 이고 status != "OK" 일 때.
    """
    if (location is None) == (pano is None):
        raise ValueError("location 또는 pano 중 하나만 지정해야 합니다.")

    if isinstance(location, tuple):
        location = f"{location[0]},{location[1]}"

    params = {
        "key": api_key or get_api_key(),
        "radius": radius,
        "source": source,
    }
    if location is not None:
        params["location"] = location
    else:
        params["pano"] = pano

    url = f"{METADATA_URL}?{urllib.parse.urlencode(params)}"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"요청 실패: {e.reason}") from e

    status = data.get("status")
    if status != "OK" and raise_on_error:
        # ZERO_RESULTS: 해당 위치에 파노라마 없음
        # NOT_FOUND: 주소를 찾을 수 없음
        # OVER_QUERY_LIMIT / REQUEST_DENIED / INVALID_REQUEST / UNKNOWN_ERROR
        message = data.get("error_message", "")
        raise RuntimeError(f"Street View metadata status={status} {message}".strip())

    return data


if __name__ == "__main__":
    import sys

    # 사용법:
    #   python -m cwvlm.collect.metadata 37.5665,126.9780
    #   python -m cwvlm.collect.metadata "서울특별시청"
    #   python -m cwvlm.collect.metadata --pano <pano_id>
    args = sys.argv[1:]
    if not args:
        query = "37.5665,126.9780"  # 서울시청 (기본 예시)
        result = get_streetview_metadata(location=query)
    elif args[0] == "--pano" and len(args) > 1:
        result = get_streetview_metadata(pano=args[1])
    else:
        result = get_streetview_metadata(location=" ".join(args))

    print(json.dumps(result, ensure_ascii=False, indent=2))
