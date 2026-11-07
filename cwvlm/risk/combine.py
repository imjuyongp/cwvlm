"""D1~D4 도메인 점수를 종합 점수로 합친다.

모델에 맡기지 않고 코드로 계산한다. 재현성 테스트에서 종합 점수의
완전일치율이 0%, 우선도 조합표 위반이 30% 로 나왔기 때문이다.
여기서 계산하면 재현율 100%, 규칙 위반 0 이 보장된다.

점수는 0 / 25 / 50 / 75 / 100 다섯 단계만 쓴다.
"""

LEVELS = (0, 25, 50, 75, 100)
HIGH = 75  # 이 값 이상이면 "높음"으로 본다


def environment_risk(d2: int | None, d3: int | None, d4: int | None) -> int | None:
    """종합 환경 위험 (D2~D4). D1 은 반영하지 않는다.

    단순 평균하지 않는다. 여러 도메인에서 위험이 함께 나타나면 더 높게 보고,
    한 도메인만 높아도 다른 도메인의 낮은 점수에 묻히지 않게 한다.
    D3(보차분리)가 보행자 위험에 가장 직접적이므로 가중이 다르다.
    """
    if d3 is None:  # 핵심 도메인이 비면 종합도 낼 수 없다
        return None

    others = [x for x in (d2, d4) if x is not None]
    d3_high = d3 >= HIGH
    other_high = [x for x in others if x >= HIGH]

    if d3_high and other_high:
        return 100                      # D3 + 다른 하나가 함께 높음
    if len(other_high) >= 2:
        return 75                       # D2·D4 만 높음 (D3 는 낮음)
    if d3_high:
        return 75                       # D3 단독. 낮게 편향된 피처라 100 으로 올리지 않는다
    if other_high:
        return 50                       # D2 또는 D4 단독
    return max([d3] + others)           # 모두 낮음 → 그중 가장 높은 단계


# 우선도 조합표. 행 = D1, 열 = 종합 환경 위험
#   좌상단(D1 높고 환경 낮음)이 100 이 되지 않게 하고,
#   우하단(D1 낮고 환경 높음)이 낮게 깎이지 않게 한다.
PRIORITY = {
    100: {0: 50, 25: 50, 50: 75, 75: 100, 100: 100},
    75:  {0: 25, 25: 25, 50: 50, 75: 75,  100: 100},
    50:  {0: 25, 25: 25, 50: 50, 75: 75,  100: 100},
    25:  {0: 0,  25: 0,  50: 25, 75: 50,  100: 75},
    0:   {0: 0,  25: 0,  50: 25, 75: 50,  100: 75},
}


def inspection_priority(d1: int | None, env: int | None) -> int | None:
    """예방적 현장점검 우선도. 환경 위험이 없으면 우선순위를 정할 수 없다."""
    if env is None:
        return None
    if d1 is None:
        d1 = 50  # 보호 수요를 모르면 중간으로 두고 환경 위험만 반영한다
    return PRIORITY[d1][env]


def reason_env(d2, d3, d4, score) -> str:
    if score is None:
        return "D3 판단 불가로 종합 환경 위험을 산출할 수 없음"
    parts = [f"D2={d2}", f"D3={d3}", f"D4={d4}"]
    high = [n for n, v in zip(("D2", "D3", "D4"), (d2, d3, d4))
            if v is not None and v >= HIGH]
    if not high:
        return f"{', '.join(parts)} — 세 도메인 모두 높음 단계 미만"
    return f"{', '.join(parts)} — {'·'.join(high)} 가 높음 단계"


def reason_priority(d1, env, score) -> str:
    if score is None:
        return "종합 환경 위험이 없어 우선도를 산출할 수 없음"
    if d1 is None:
        return f"D1 판단 불가, 환경위험={env} 만 반영"
    return f"D1={d1}, 환경위험={env} 조합표 적용"


def apply(record: dict) -> dict:
    """모델이 낸 D1~D4 에 종합 점수를 계산해 붙인다."""
    get = lambda k: (record.get(k) or {}).get("score")
    d1, d2, d3, d4 = get("D1"), get("D2"), get("D3"), get("D4")

    env = environment_risk(d2, d3, d4)
    pri = inspection_priority(d1, env)

    record["environment_risk"] = {"score": env, "reason": reason_env(d2, d3, d4, env)}
    record["inspection_priority"] = {"score": pri, "reason": reason_priority(d1, env, pri)}
    return record


if __name__ == "__main__":
    # 조합표가 두 가지 원칙을 지키는지 확인한다
    assert environment_risk(75, 100, 50) == 100      # D3 + D2 높음
    assert environment_risk(75, 25, 75) == 75        # D2·D4 만 높음
    assert environment_risk(25, 100, 25) == 75       # D3 단독은 100 으로 올리지 않음
    assert environment_risk(100, 25, 0) == 50        # D2 단독
    assert environment_risk(50, 50, 25) == 50        # 모두 낮음
    assert environment_risk(50, None, 50) is None    # D3 없음

    assert inspection_priority(100, 0) == 50, "높은 D1 만으로 우선도를 올리지 않는다"
    assert inspection_priority(0, 100) == 75, "낮은 D1 으로 높은 환경위험을 지우지 않는다"
    assert inspection_priority(100, 100) == 100
    assert inspection_priority(0, 0) == 0
    assert inspection_priority(50, None) is None

    for d1 in LEVELS:
        for env in LEVELS:
            assert PRIORITY[d1][env] in LEVELS
    print("조합 규칙 검증 통과")
