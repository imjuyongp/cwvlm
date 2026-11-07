"""VLM 호출 백엔드 — Ollama(로컬)와 OpenRouter(API)를 같은 인터페이스로 감싼다.

둘 다 judge(image_path) -> dict 를 제공하므로 호출부는 백엔드를 몰라도 된다.
"""

import base64
import json
import os
from pathlib import Path

from cwvlm.config import load_dotenv
from cwvlm.vlm.prompt import PROMPT, RESPONSE_SCHEMA

# ---------------------------------------------------------------- 공통


class Backend:
    """judge(image_path) -> dict 를 제공하는 백엔드의 기반 클래스."""

    name = "base"

    def judge(self, image_path: Path) -> dict:
        raise NotImplementedError


# ---------------------------------------------------------------- Ollama

class OllamaBackend(Backend):
    """로컬 Ollama. 느리지만 무료이며 프롬프트 반복 시험에 적합."""

    name = "ollama"
    #  qwen3-vl 은 답변 전 thinking 에 약 2,000 토큰을 쓴다. 여유 없이 자르면
    #  추론 도중 끊겨 content 가 빈 문자열로 온다.
    OPTIONS = {"temperature": 0, "num_ctx": 8192, "num_predict": 3000}

    def __init__(self, model: str = "qwen3-vl:8b"):
        import ollama  # 지연 임포트: API 만 쓸 때는 필요 없다

        self._ollama = ollama
        self.model = model

    def judge(self, image_path: Path) -> dict:
        resp = self._ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": PROMPT, "images": [str(image_path)]}],
            format=RESPONSE_SCHEMA,
            options=self.OPTIONS,
        )
        content = resp["message"]["content"].strip()
        if not content:
            raise RuntimeError(
                f"빈 응답 (done_reason={resp.get('done_reason')}, "
                f"prompt={resp.get('prompt_eval_count')}, eval={resp.get('eval_count')})"
            )
        return json.loads(content)


# ---------------------------------------------------------------- OpenRouter

class OpenRouterBackend(Backend):
    """OpenRouter API. thinking 없는 instruct 계열을 쓰면 빠르고 저렴하다."""

    name = "openrouter"
    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, model: str = "qwen/qwen3-vl-235b-a22b-instruct"):
        from openai import OpenAI  # 지연 임포트

        load_dotenv()
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY 가 .env 또는 환경변수에 없습니다.")
        self.client = OpenAI(base_url=self.BASE_URL, api_key=key)
        self.model = model
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

    MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp"}

    def judge(self, image_path: Path) -> dict:
        b64 = base64.b64encode(image_path.read_bytes()).decode()
        mime = self.MIME.get(image_path.suffix.lower(), "image/jpeg")
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "road_features",
                    "strict": True,
                    "schema": RESPONSE_SCHEMA,
                },
            },
            temperature=0,
            max_tokens=800,
        )
        if resp.usage:
            self.usage["prompt_tokens"] += resp.usage.prompt_tokens
            self.usage["completion_tokens"] += resp.usage.completion_tokens
            self.usage["calls"] += 1

        content = (resp.choices[0].message.content or "").strip()
        if not content:
            raise RuntimeError(f"빈 응답 (finish_reason={resp.choices[0].finish_reason})")
        return json.loads(content)


# ---------------------------------------------------------------- 선택

DEFAULT_MODELS = {
    "ollama": "qwen3-vl:8b",
    "openrouter": "qwen/qwen3-vl-235b-a22b-instruct",
}


def make_backend(kind: str, model: str | None = None) -> Backend:
    model = model or DEFAULT_MODELS[kind]
    if kind == "ollama":
        return OllamaBackend(model)
    if kind == "openrouter":
        return OpenRouterBackend(model)
    raise ValueError(f"알 수 없는 백엔드: {kind}")
