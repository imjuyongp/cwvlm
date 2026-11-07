## 구조

```
cwvlm/
├── config.py               HEADINGS, 저장소 루트, .env 로더
├── collect/                1. 수집
│   ├── metadata.py         Street View 메타데이터 API
│   ├── image.py            Street View 이미지 API, URL 조립
│   ├── check_spots.py      전체 스팟 로드뷰 존재 여부 조회
│   ├── download_streetview.py   pano × 4방향 이미지 다운로드
│   └── download_drive.py   CSV 의 이미지 URL(Drive 등) 다운로드 — 검증셋용
├── vlm/                    2. VLM 피쳐
│   ├── prompt.py           프롬프트 + JSON 스키마
│   ├── backend.py          OpenRouter / Ollama 백엔드
│   ├── extract.py          방향별 판독 → JSONL
│   ├── merge.py            스팟 단위 집계(aggregate) → 원본 CSV 병합
│   ├── export_features.py  피쳐 컬럼만 별도 CSV 로
│   └── evaluate.py         정답셋 대조 (Cohen's κ, QWK)
├── risk/                   3. 위험도 채점
│   ├── domains.py          D1~D4 규칙 채점, THRESHOLDS
│   ├── combine.py          종합 환경위험 · 현장점검 우선도 (+ assert 검증)
│   ├── prompt.py           현장확인사항 서술 프롬프트
│   ├── score.py            채점 실행 (점수는 코드, 서술만 LLM)
│   ├── consistency.py      반복 실행 재현성 측정
│   └── export.py           최종 CSV 산출
└── labeling/               사람 검수
    ├── label_sample.py     정답셋 라벨링 표본
    └── review_sample.py    '확인 필요' 지점 검수 표본
```

## 실행

모든 명령은 **저장소 루트에서** 실행한다. `data/` 경로는 실행 위치 기준이다.

```bash
pip install -e .            # 로컬 Ollama 도 쓰려면: pip install -e ".[local]"
cp .env.example .env        # GOOGLE_MAPS_API_KEY, OPENROUTER_API_KEY

python -m cwvlm.collect.check_spots
python -m cwvlm.collect.download_streetview
python -m cwvlm.vlm.extract --csv data/streetview_spots_checked.csv
python -m cwvlm.vlm.merge
python -m cwvlm.vlm.evaluate                  # 정답셋 대조
# (공공데이터 결합 → data/최종_데이터셋_VLM_공공데이터_out.csv)
python -m cwvlm.risk.combine                  # 조합 규칙 assert 검증
python -m cwvlm.risk.score --backend openrouter
python -m cwvlm.risk.export
```

데이터가 바뀌면 `cwvlm/risk/domains.py` 의 `THRESHOLDS` 를 다시 산출해야 한다.
