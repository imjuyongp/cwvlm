"""현장점검 항목 서술용 프롬프트.

점수(D1~D4, 종합)는 risk_domains.py / risk_combine.py 가 규칙대로 계산한다.
모델에게 같은 규칙을 따르게 했을 때 준수율이 53~80% 에 그쳐, 점수 산출은
코드로 옮기고 모델에는 서술만 맡긴다.

모델이 하는 일: 계산된 점수와 입력값을 보고 현장에서 확인할 항목 3개를 쓴다.
"""

# 모델에 넘길 입력 컬럼. 이 목록에 없는 컬럼은 전달하지 않는다.
#   제외 이유
#     facility_name/types  시설명 지식 유입, 도메인 정의에 없음
#     protection_review    검토 상태값이지 위험 피처가 아님
#     pano_id              231행이 177개를 공유해 키로 부적합
#     판정/확신도           상수이거나 변별력 없음
#     사진에서 확인한 근거    VLM 서술문이 앵커링 유발
INPUT_COLUMNS = [
    "spot_id", "세부 유형",
    "crosswalk", "median_barrier",
    "ped_sep_median", "ped_sep_min",
    "lane_clarity_median", "lane_clarity_min",
    "n_assessable",
    "intersections_300m", "nl_max_lanes_300m", "nl_max_spd_300m",
    "cameras_300m", "streetlights_300m",
    "population",
]

SCORE_LEVELS = [0, 25, 50, 75, 100]

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "field_checks": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 3,
        },
    },
    "required": ["field_checks"],
}


PROMPT = """[역할]
너는 고령 보행자 교통안전을 평가하는 분석가다.
아래 지점의 보행환경 데이터와 이미 산출된 위험 점수를 보고,
현장에 나가서 무엇을 확인해야 하는지 정한다.

[주의]
- 점수는 이미 규칙에 따라 계산됐다. 점수를 다시 매기거나 반박하지 않는다.
- 입력에 없는 사실을 근거로 쓰지 않는다. 지역, 지명, 동네 특성을 추측하지 않는다.
- 사고 발생 여부나 법적 지정 가능 여부를 판단하지 않는다.

[피처 뜻]
crosswalk          사진에 횡단보도(흰색 얼룩말 무늬)가 보이는지. no 는 보이는
                   범위에 없다는 뜻이며 300m 전체의 부재를 뜻하지 않는다.
median_barrier     양방향 통행이 나뉘어 있는지(중앙선 또는 구조물).
                   대부분 페인트 중앙선이므로 보행자 대피공간이 아니다.
ped_sep_min/median 보행 공간과 차도의 분리 (0 분리없음 / 1 노면표시만 /
                   2 연석 / 3 물리적 차단). min 이 가장 취약한 방향이다.
lane_clarity_*     차선 표시 명확도 (0 없음 / 1 흔적만 / 2 부분마모 / 3 선명).
                   이면도로는 차선이 없는 것이 정상이다.
n_assessable       사진 4방향 중 도로가 보여 판단할 수 있었던 방향 수.
intersections_300m / nl_max_lanes_300m / nl_max_spd_300m
                   반경 300m 의 교차로 수 / 최대 편도 차로 수 / 최고 제한속도.
                   사진 속 도로가 아닐 수 있다.
cameras_300m / streetlights_300m
                   반경 300m 의 무인단속카메라 / 가로등 수.
                   0 은 실제 부재인지 미수집인지 구분할 수 없다.
population         반경 500m 고령인구. 실제 보행량이 아니라 대리 지표다.

[도메인]
D1 보호 수요        고령자가 얼마나 많은가
D2 횡단 위험        길을 건너기 어려운가
D3 보행 공간 위험    차와 섞여서 걷는가
D4 운전자·차량 위험  운전자가 못 보거나 못 멈추는가
점수는 0 / 25 / 50 / 75 / 100 다섯 단계이고 높을수록 위험하다.

[지점 데이터]
{spot_data}

[산출된 점수]
{scores}

[해야 할 일]
현장에서 확인할 항목을 1~3개 쓴다.
- 점수를 높인 피처를 직접 겨냥한다. 점수가 낮은 항목은 넣지 않는다.
- 사진이나 공공데이터로는 확인할 수 없어 현장에 가야만 알 수 있는 것을 쓴다.
  (예: 사진에 안 보인 방향의 보도 상태, 0 으로 기록된 시설의 실제 설치 여부,
   기록된 제한속도와 실제 주행 양상의 차이)
- 각 항목은 한국어 한 문장으로 쓰고, 근거가 된 컬럼명을 문장 안에 포함한다.
- 일반론("교통안전 점검 필요")을 쓰지 않는다.

[출력] 아래 JSON 형식으로만 답한다. 다른 문장은 쓰지 않는다.

{
  "field_checks": ["...", "...", "..."]
}"""


def build_prompt(row: dict, scored: dict) -> str:
    """CSV 한 행과 계산된 점수로 프롬프트를 만든다."""
    data = "\n".join(f"{c} = {row.get(c, '')}" for c in INPUT_COLUMNS)
    lines = []
    for k in ("D1", "D2", "D3", "D4"):
        d = scored[k]
        lim = f"  (한계: {d['limitation']})" if d["limitation"] else ""
        lines.append(f"{k} = {d['score']}{lim}")
    lines.append(f"종합 환경 위험 = {scored['environment_risk']['score']}")
    lines.append(f"예방적 현장점검 우선도 = {scored['inspection_priority']['score']}")
    return (PROMPT
            .replace("{spot_data}", data)
            .replace("{scores}", "\n".join(lines)))
