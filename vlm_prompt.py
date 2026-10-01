"""도로 안전 피쳐 추출 + 도로 후보 검수용 VLM 프롬프트와 JSON 스키마.

두 가지를 함께 판단한다.

(1) 도로 후보 검수 — 로드뷰가 촬영된 지점이 노인보호구역 지정 검토 대상이
    될 수 있는 도로인지. 아파트 단지 내부 통로·공원 산책로 등을 걸러낸다.
      road_candidate, road_candidate_type, confidence,
      evidence_road_candidate, needs_review_reason

(2) 도로 안전 피쳐 4종
      crosswalk               횡단보도 유무 (yes/no)
      median_barrier          중앙 분리 유무 (yes/no) — 중앙선 또는 분리 구조물
      lane_marking_clarity    차선 표시 명확도 (0~3)
      pedestrian_separation   보행-차도 분리 수준 (0~3)
"""

# 판정 값. "사진 확인 불가" 는 파일 누락·열람 실패 시 코드가 부여한다
# (vlm_extract.py 의 error 경로). 모델은 이미지가 손상되어 내용을 식별할 수
# 없을 때만 사용한다.
ROAD_CANDIDATE_VALUES = ["도로 후보", "제외", "확인 필요", "사진 확인 불가"]
CONFIDENCE_VALUES = ["높음", "보통", "낮음"]

# Ollama / OpenRouter 의 구조화 출력에 넘길 JSON 스키마
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        # --- 도로 후보 검수 ---
        "road_candidate": {"type": "string", "enum": ROAD_CANDIDATE_VALUES},
        "road_candidate_type": {"type": "string"},
        "confidence": {"type": "string", "enum": CONFIDENCE_VALUES},
        "evidence_road_candidate": {"type": "string"},
        "needs_review_reason": {"type": "string"},
        # --- 도로 안전 피쳐 ---
        "road_type": {"type": "string", "enum": ["arterial", "alley", "unclear"]},
        "assessable": {"type": "boolean"},
        "crosswalk": {"type": "string", "enum": ["yes", "no"]},
        "median_barrier": {"type": "string", "enum": ["yes", "no"]},
        "lane_marking_clarity": {"type": ["integer", "null"], "minimum": 0, "maximum": 3},
        "pedestrian_separation": {"type": ["integer", "null"], "minimum": 0, "maximum": 3},
        # 항목별 근거를 따로 받는다. 하나로 묶으면 모델이 첫 항목만 서술한다.
        "evidence_crosswalk": {"type": "string"},
        "evidence_median_barrier": {"type": "string"},
        "evidence_lane_marking": {"type": "string"},
        "evidence_pedestrian_separation": {"type": "string"},
    },
    "required": [
        "road_candidate", "road_candidate_type", "confidence",
        "evidence_road_candidate", "needs_review_reason",
        "road_type", "assessable", "crosswalk", "median_barrier",
        "lane_marking_clarity", "pedestrian_separation",
        "evidence_crosswalk", "evidence_median_barrier",
        "evidence_lane_marking", "evidence_pedestrian_separation",
    ],
}

EVIDENCE_FIELDS = [
    "evidence_road_candidate", "evidence_crosswalk", "evidence_median_barrier",
    "evidence_lane_marking", "evidence_pedestrian_separation",
]

# 결과 CSV 로 내보낼 때 쓸 한글 컬럼명
CSV_COLUMN_NAMES = {
    "road_candidate": "판정",
    "road_candidate_type": "세부 유형",
    "evidence_road_candidate": "사진에서 확인한 근거",
    "confidence": "확신도(높음/보통/낮음)",
    "needs_review_reason": "추가 확인이 필요한 이유",
}

PROMPT = """당신은 도로 안전 시설을 판독하는 전문가다. 주어진 사진 1장을 보고
(A) 도로 후보 검수와 (B) 도로 안전 피쳐 판단을 모두 수행하라.

사진은 특정 지점에서 촬영된 로드뷰의 한 방향이다.
판단은 오직 이 사진에 보이는 것만을 근거로 하라. 사진 밖의 지식이나
지역에 대한 추측을 끌어오지 마라.

================================================================
(A) 도로 후보 검수
================================================================

목적은 노인보호구역 지정 검토 대상이 될 수 있는 도로를 남기고,
도로가 아닌 지점을 제외하는 것이다.

가장 중요한 원칙:
판정 대상은 사진 속 먼 곳에 보이는 도로가 아니라, 이 사진이 촬영된 지점이다.
멀리 도로가 보이더라도 촬영 지점 자체가 시설 내부라면 도로 후보가 아니다.

1. road_candidate — 다음 넷 중 하나
   - "도로 후보": 촬영 지점이 일반적인 도로 구간 또는 교차로로 보이는 경우.
     차도와 인도가 함께 있는 도로뿐 아니라, 인도가 따로 없는 이면도로도 포함한다.
   - "제외": 촬영 지점이 아파트 단지 내부 통로, 공원 산책로, 주차장 내부 통로,
     건물 부지 안의 차량 통로 등 주변도로가 아닌 공간으로 보이는 경우.
   - "확인 필요": 도로와 시설 내부 통로의 경계가 불명확하거나, 사진만으로
     촬영 지점이 도로인지 판단하기 어려운 경우.
   - "사진 확인 불가": 사진이 손상되었거나 내용을 식별할 수 없어 판정 불가한 경우.

   판정 시 주의:
   - 아파트·공원·주차장이 도로 옆에 보인다는 이유만으로 제외하지 마라.
     촬영 지점 자체가 시설 내부인지, 시설에 접한 일반 도로인지 구분하라.
   - 인도나 횡단보도가 보이더라도 그것이 연결된 도로 구간을 기준으로 판단하라.
   - 공원 안의 독립적인 산책로는 도로 후보에 넣지 마라.
   - 사진만으로 법적 도로 여부나 노인보호구역의 최종 지정 가능성을 확정하지 마라.
     도로처럼 보이지만 시설 내부도로일 가능성을 배제할 수 없다면 "확인 필요"로 하라.
   - 노인 보행수요, 주변 시설 요건, 사고 위험도는 이 판정에 섞지 마라.
     이번 작업은 도로 후보 여부만 검수하는 단계다.

2. road_candidate_type — 촬영 지점의 세부 유형을 한국어 짧은 명사구로 쓰라.
   예: "이면도로", "교차로", "왕복2차로 도로", "아파트 단지 내부 통로",
       "공원 산책로", "주차장 내부 통로", "건물 부지 내 차량 통로", "식별 불가"

3. confidence — 이 판정에 대한 확신도. "높음" / "보통" / "낮음" 중 하나.

4. evidence_road_candidate — 촬영 지점을 그렇게 판정한 근거를 한국어 한 문장으로.
   사진에서 실제로 본 것(노면 종류, 차선, 연석, 차단기, 단지 구조물 등)을 쓰라.

5. needs_review_reason — "확인 필요" 또는 "사진 확인 불가" 일 때만 그 이유를
   한국어 한 문장으로 쓰라. 그 외에는 빈 문자열("")로 두라.

================================================================
(B) 도로 안전 피쳐
================================================================

road_candidate 가 "제외" 나 "사진 확인 불가" 이더라도, 노면이 보이면
아래 항목을 그대로 판단하라. (집계 단계에서 걸러낸다.)

6. road_type — 도로 종류
   - arterial: 차로 구분이 있는 일반 도로 (왕복 2차로 이상)
   - alley: 이면도로, 골목, 마을안길 (차로 구분이 없는 좁은 길)
   - unclear: 도로가 보이지 않거나 종류를 알 수 없음

7. assessable — 도로 노면이 보여서 판단이 가능한가 (true/false)
   노면이 화면의 일부에만 보여도 그 부분으로 판단할 수 있으면 true 로 하라.
   차도 노면이 전혀 보이지 않을 때만(건물 내부, 실내, 벽면·하늘만 보임,
   초목에 완전히 가려짐) false 로 하라.
   false 이면 lane_marking_clarity 와 pedestrian_separation 은 null 로 하라.

8. crosswalk — 횡단보도 (yes/no)
   노면에 흰색 굵은 줄무늬(얼룩말 무늬)가 보이면 yes.
   정지선만 있거나 자전거횡단도(점선)만 있으면 no.

9. median_barrier — 중앙 분리 (yes/no)
   판단 기준은 "차가 다니는 방향(상행/하행)을 나누는 것이 사진에서 명확히
   보이는가" 이다. 구조물이든 노면 표시든 상관없다.

   yes 로 하는 경우:
   - 중앙선이 보일 때. 도로 중앙을 따라 길게 이어진 황색 실선·점선·복선 등.
   - 중앙분리대 구조물이 보일 때. 화단, 콘크리트 벽, 플라스틱 분리봉,
     중앙섬, 도로 중앙에 설치된 방호 난간·울타리.

   no 로 하는 경우:
   - 도로 중앙에 선도 구조물도 없을 때.
   - 일방통행 도로처럼 나눌 방향 자체가 없어 중앙 표시가 없을 때.
   - 가장자리선만 있고 중앙을 나누는 선은 없을 때.

   주의 — 다음은 중앙선이 아니다. 색만 보고 판단하지 마라:
   - 도로 가장자리나 연석을 따라 그어진 흰색 선(가장자리선).
   - 연석·보도 경계를 따라 그어진 황색 실선·복선(주정차금지선).
     한국 도로에서 흔하다. 황색이라도 도로 가장자리에 붙어 있으면 중앙선이 아니다.
   - 주차 구획선, 정지선, 노면 화살표.
   반드시 그 선이 차도의 한가운데를 따라 이어지면서
   반대 방향으로 가는 차로를 나누고 있는지 확인하라.

10. lane_marking_clarity — 차선 표시 명확도 (0~3 정수)
   0 = 노면에 차선이 전혀 없음
   1 = 선의 흔적만 남음 (대부분 마모·퇴색되어 끊겨 보임)
   2 = 식별 가능하나 부분 마모 (선은 이어지나 색이 바래거나 일부 지워짐)
   3 = 선명 (흰색·황색이 뚜렷하고 끊김 없이 이어짐)
   중앙선·차로구분선뿐 아니라 가장자리선도 차선으로 인정한다.

11. pedestrian_separation — 보행 공간과 차도의 분리 수준 (0~3 정수)
   0 = 분리 없음 (보도가 없어 보행자가 차도를 공유)
   1 = 노면표시만 (페인트 선이나 컬러 포장으로만 구분, 높이 차 없음)
   2 = 연석 분리 (연석·단차로 높이가 구분되나 차량 진입 차단물 없음)
   3 = 물리적 차단 (가드레일·펜스·볼라드·화단 등이 설치됨)

12. 근거 — 항목마다 별도 필드에 한국어 한 문장으로 서술하라.
   각 근거는 반드시 해당 항목만 설명해야 한다. 다른 항목 얘기를 쓰지 마라.
   - evidence_crosswalk: 횡단보도 판단의 근거
   - evidence_median_barrier: 중앙분리대 판단의 근거
   - evidence_lane_marking: 차선 명확도 점수의 근거
   - evidence_pedestrian_separation: 보행 분리 점수의 근거
   판단 불가(assessable=false)인 항목은 무엇이 가려서 못 봤는지 쓰라.

[공통 판단 규칙]
- 점수는 반드시 위에 정의된 정수 중 하나로만 답하라.
- 추정하지 말고 사진에서 실제로 보이는 것만 근거로 삼아라.
- 사진에 일부만 보이더라도 보이는 범위 안에서 판단하라.
- 애매하면 낮은 점수를 선택하라.
- 사진이 기울어져 있거나 아래를 향해 있어도 보이는 범위로 판단하라.
- 사진 하단의 Google 워터마크와 저작권 표시는 무시하라.

JSON 으로만 답하라."""
