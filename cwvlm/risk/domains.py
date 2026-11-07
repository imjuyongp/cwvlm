"""D1~D4 도메인 점수를 규칙대로 계산한다.

프롬프트에 쓴 규칙이 조회표 수준으로 결정론적이 되어, 모델에게 따라 하게 하는
대신 그대로 코드로 옮겼다. 모델은 같은 규칙을 53~80% 만 지켰다.
여기서 계산하면 재현율과 규칙 준수율이 모두 100% 가 된다.

점수는 0 / 25 / 50 / 75 / 100 다섯 단계만 쓴다.
임계값은 data/최종_데이터셋_VLM_공공데이터_out.csv 231곳의 백분위에서 나왔다.
데이터가 바뀌면 THRESHOLDS 를 다시 계산해야 한다.
"""

LEVELS = (0, 25, 50, 75, 100)

# 231곳 백분위 (10% / 25% / 50% / 75% / 90%)
THRESHOLDS = {
    "population": (435, 957, 1827, 2622, 3367),
    "intersections_300m": (9, 18, 33, 49, 57),
    "cameras_300m": (0, 1, 2, 5, 8),
    "streetlights_300m": (12, 40, 70, 104, 131),
}


def _num(row: dict, col: str) -> float | None:
    v = row.get(col, "")
    if v in ("", None):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _step(down: int) -> int:
    """한 단계 내린다. 0 밑으로는 내려가지 않는다."""
    return max(0, down - 25)


def _up(v: int) -> int:
    return min(100, v + 25)


# ---------------------------------------------------------------- D1

def d1_protection_demand(row: dict) -> tuple[int | None, list[str]]:
    """보호 수요. 반경 500m 고령인구의 분포 위치를 그대로 단계로 쓴다."""
    p = _num(row, "population")
    if p is None:
        return None, []
    p10, p25, _, p75, p90 = THRESHOLDS["population"]
    score = (0 if p < p10 else 25 if p < p25 else 50 if p < p75
             else 75 if p < p90 else 100)
    return score, [f"population={row['population']}"]


# ---------------------------------------------------------------- D2

def _intersection_step(n: float) -> int:
    p10, p25, _, p75, p90 = THRESHOLDS["intersections_300m"]
    return 0 if n <= p10 else 25 if n <= p25 else 50 if n <= p75 else 75 if n <= p90 else 100


def _lane_step(lanes: float) -> int:
    """편도 차로 수. 1차로가 분포 하위, 5차로 이상이 상위다."""
    return {1: 0, 2: 25, 3: 50, 4: 75}.get(int(lanes), 100)


def d2_crossing_risk(row: dict) -> tuple[int | None, list[str]]:
    """횡단 위험.

    교차로 수와 차로 수 중 부담이 큰 쪽이 난이도를 정한다(평균 내지 않는다).
    crosswalk=yes 는 건널 수단이 실제로 관측된 것이므로 한 단계 낮춘다.
    crosswalk=no 는 보이는 범위에 없다는 뜻일 뿐이라 단계를 올리지 않는다.
    median_barrier 는 대피공간이 아니라 차로 구분 신호이므로 단계를 움직이지 않는다.
    """
    inters = _num(row, "intersections_300m")
    lanes = _num(row, "nl_max_lanes_300m")
    if inters is None or lanes is None:
        return None, []

    score = max(_intersection_step(inters), _lane_step(lanes))
    ev = [f"intersections_300m={row['intersections_300m']}",
          f"nl_max_lanes_300m={row['nl_max_lanes_300m']}",
          f"crosswalk={row.get('crosswalk', '')}",
          f"median_barrier={row.get('median_barrier', '')}"]

    if row.get("crosswalk") == "yes":
        score = _step(score)
    return score, ev


# ---------------------------------------------------------------- D3

def d3_walkspace_risk(row: dict) -> tuple[int | None, list[str]]:
    """보행 공간 위험.

    ped_sep_min(가장 취약한 방향)이 주 지표다. median 은 그 취약함이
    지점 전체인지 한 방향뿐인지 구분하는 데만 쓴다.
    ped_sep 만 보고 판단하므로 100 은 주지 않는다 — 낮게 편향된 피처다.
    """
    mn = _num(row, "ped_sep_min")
    if mn is None:
        return None, []
    score = {0: 75, 1: 50, 2: 25, 3: 0}[int(mn)]

    md = _num(row, "ped_sep_median")
    ev = [f"ped_sep_min={row['ped_sep_min']}",
          f"ped_sep_median={row.get('ped_sep_median', '')}",
          f"n_assessable={row.get('n_assessable', '')}"]

    # n_assessable 이 2 이하면 median 과 min 이 구조적으로 같아 의미가 없다
    n = _num(row, "n_assessable")
    if md is not None and n is not None and n >= 3 and md > mn:
        score = _step(score)  # 한 방향만 취약
    return score, ev


# ---------------------------------------------------------------- D4

ALLEY = "이면도로"


def _speed_step(spd: float) -> int:
    return 25 if spd <= 50 else 50 if spd <= 60 else 75 if spd <= 70 else 100


def _lane_clarity_step(v: float) -> int:
    return {0: 75, 1: 50, 2: 25, 3: 0}[int(v)]


def d4_driver_risk(row: dict) -> tuple[int | None, list[str]]:
    """운전자·차량 위험.

    이면도로는 차선이 없는 게 정상이므로 lane_clarity 를 빼고 속도만 본다.
    왕복2차로·교차로는 차선 마모가 실제 위험 신호이므로 속도와 함께 본다.
    카메라·가로등은 보조 근거라 한 단계까지만 움직인다.
    """
    spd = _num(row, "nl_max_spd_300m")
    if spd is None:
        return None, []

    road = row.get("세부 유형", "")
    ev = [f"nl_max_spd_300m={row['nl_max_spd_300m']}", f"세부 유형={road}"]
    score = _speed_step(spd)

    lane_min = _num(row, "lane_clarity_min")
    if road != ALLEY and lane_min is not None:
        score = max(score, _lane_clarity_step(lane_min))
        ev.append(f"lane_clarity_min={row['lane_clarity_min']}")

    # 보조: 카메라와 가로등이 둘 다 분포 하위 25% 이내일 때만 한 단계 올린다
    cam, lit = _num(row, "cameras_300m"), _num(row, "streetlights_300m")
    if (cam is not None and lit is not None
            and cam <= THRESHOLDS["cameras_300m"][1]
            and lit <= THRESHOLDS["streetlights_300m"][1]):
        score = _up(score)
    ev += [f"cameras_300m={row.get('cameras_300m', '')}",
           f"streetlights_300m={row.get('streetlights_300m', '')}"]
    return score, ev


# ---------------------------------------------------------------- 한계·충분성

def limitations(row: dict) -> dict[str, str]:
    """기계적으로 판정 가능한 한계를 도메인별로 붙인다."""
    out = {k: [] for k in ("D1", "D2", "D3", "D4")}

    if _num(row, "비공개격자수") not in (None, 0):
        out["D1"].append("비공개 격자가 포함된 보정값")
    if row.get("crosswalk") == "no":
        out["D2"].append("crosswalk=no 는 사진에 보이는 범위에 없다는 뜻이며 "
                         "반경 300m 전체의 부재를 뜻하지 않음")
    n = _num(row, "n_assessable")
    if n is not None and n <= 1:
        out["D3"].append("n_assessable=1 로 한 방향만 보고 매긴 값이라 신뢰도가 낮음")
    elif n is not None and n <= 2:
        out["D3"].append("n_assessable=2 로 median 과 min 이 구조적으로 동일")
    zero = [c for c in ("cameras_300m", "streetlights_300m") if _num(row, c) == 0]
    if zero:
        out["D4"].append(f"{', '.join(zero)}=0 은 실제 부재인지 미수집인지 구분 불가")
    return {k: " / ".join(v) for k, v in out.items()}


def data_sufficiency(row: dict) -> str:
    n = _num(row, "n_assessable") or 0
    zero = sum(1 for c in ("cameras_300m", "streetlights_300m") if _num(row, c) == 0)
    if n <= 1 or zero == 2:
        return "크게 부족"
    if n <= 2 or zero == 1:
        return "일부 부족"
    return "충분"


# ---------------------------------------------------------------- 진입점

def score_row(row: dict) -> dict:
    """한 행의 D1~D4 와 근거·한계·자료 충분성을 계산한다."""
    lim = limitations(row)
    out = {"spot_id": row["spot_id"]}
    for key, fn in (("D1", d1_protection_demand), ("D2", d2_crossing_risk),
                    ("D3", d3_walkspace_risk), ("D4", d4_driver_risk)):
        score, ev = fn(row)
        out[key] = {"score": score, "evidence": ev, "limitation": lim[key]}
    out["data_sufficiency"] = data_sufficiency(row)
    return out


if __name__ == "__main__":
    import csv

    with open("data/최종_데이터셋_VLM_공공데이터_out.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    import collections
    dist = {k: collections.Counter() for k in ("D1", "D2", "D3", "D4")}
    for r in rows:
        s = score_row(r)
        for k in dist:
            dist[k][s[k]["score"]] += 1
    print(f"{len(rows)}곳 채점 결과")
    for k, c in dist.items():
        print(f"  {k}  " + "  ".join(f"{lv}:{c.get(lv, 0):>3}" for lv in LEVELS))
