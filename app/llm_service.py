from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ServiceUnavailableError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def settings() -> dict[str, str]:
    values = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    for key in ("LLM_API_KEY", "NVIDIA_API_KEY", "NVIDIA_MODEL", "NVIDIA_BASE_URL"):
        if os.getenv(key):
            values[key] = os.environ[key]
    return values


def available() -> bool:
    config = settings()
    return bool(config.get("LLM_API_KEY") or config.get("NVIDIA_API_KEY"))


def ask_json(system: str, prompt: str, max_tokens: int = 1400) -> dict:
    config = settings()
    key = config.get("LLM_API_KEY") or config.get("NVIDIA_API_KEY")
    if not key:
        raise RuntimeError(".env에 API 키를 입력하세요.")
    base = config.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
    parsed_base = urllib.parse.urlsplit(base)
    if parsed_base.scheme != "https" or not parsed_base.netloc or parsed_base.username or parsed_base.password:
        raise RuntimeError("AI API 주소에는 안전한 HTTPS 주소를 사용하세요.")
    payload = json.dumps({
        "model": config.get("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "temperature": 0.3, "top_p": 0.95, "max_tokens": max_tokens,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(base + "/chat/completions", data=payload, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    opener = urllib.request.build_opener(NoRedirect)
    for attempt in range(4):
        try:
            with opener.open(request, timeout=90) as response:
                body = response.read(1_000_001)
            if len(body) > 1_000_000:
                raise RuntimeError("AI 응답이 허용 크기를 초과했습니다.")
            try:
                result = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RuntimeError("AI 응답 형식이 올바르지 않습니다.") from exc
            break
        except urllib.error.HTTPError as exc:
            if exc.code in RETRYABLE_STATUS and attempt < 3:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = min(10, float(retry_after)) if retry_after and retry_after.isdigit() else 2 ** attempt
                time.sleep(delay)
                continue
            if exc.code in RETRYABLE_STATUS:
                raise ServiceUnavailableError("NVIDIA 모델 서비스가 현재 혼잡합니다. 잠시 후 다시 시도해 주세요. 학습과 채점은 계속 사용할 수 있습니다.") from exc
            if exc.code in {401, 403}:
                raise RuntimeError("NVIDIA API 인증에 실패했습니다. .env의 키와 모델 접근 권한을 확인하세요.") from exc
            raise RuntimeError(f"NVIDIA API가 요청을 처리하지 못했습니다 (HTTP {exc.code}).") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise ServiceUnavailableError("NVIDIA API 연결이 일시적으로 불안정합니다. 잠시 후 다시 시도해 주세요.") from exc
    try:
        content = result["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise RuntimeError("AI 응답 형식이 올바르지 않습니다.") from exc
    if not isinstance(content, str):
        raise RuntimeError("AI 응답에 텍스트가 없습니다.")
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("AI가 올바른 JSON을 반환하지 않았습니다.") from exc


def analyze_wrong(question: str, answer: str, user_answer: str, category: str, subcategory: str) -> dict:
    return ask_json(
        '정보처리기사 실기 학습 코치다. 입력된 복원 답안은 틀릴 수 있다. 반드시 JSON 객체만 반환한다. 키: cause, weak_concepts(문자열 배열), severity(0~1), feedback.',
        json.dumps({"question": question[:5000], "correct_answer": answer[:1500],
                    "user_answer": user_answer[:1000], "category": category,
                    "subcategory": subcategory}, ensure_ascii=False),
    )


def generate_question(references: list[dict], category: str, subcategory: str,
                      difficulty: int, mode: str) -> dict:
    return ask_json(
        '정보처리기사 실기 연습문제를 새로 만든다. 참고 문제를 복사하거나 숫자만 바꾸지 않는다. 명확한 정답 하나를 갖는 독립적인 문제를 만든다. JSON 객체만 반환한다. 키: question_text, answer, explanation, concepts(문자열 배열).',
        json.dumps({"mode": mode, "category": category, "subcategory": subcategory,
                    "difficulty": difficulty, "references": references}, ensure_ascii=False),
        max_tokens=2200,
    )


def validate_question(generated: dict, category: str, subcategory: str) -> dict:
    return ask_json(
        '독립적인 정보처리기사 실기 문제 검수자다. 실제로 문제를 풀어 정답, 모호성, 코드/SQL 유효성, 개념 적합성을 확인한다. JSON 객체만 반환한다. 키: valid(불리언), answer_correct(불리언), ambiguity(불리언), issues(문자열 배열).',
        json.dumps({"category": category, "subcategory": subcategory,
                    "generated": generated}, ensure_ascii=False),
    )


def explain_concept(category: str, subcategory: str, example_question: str) -> dict:
    return ask_json(
        '정보처리기사 실기 학습용 짧은 이론을 작성한다. JSON 객체만 반환한다. title, summary, example, common_mistakes의 값은 모두 문자열로 작성한다.',
        json.dumps({"category": category, "subcategory": subcategory,
                    "example_question": example_question[:2000]}, ensure_ascii=False),
    )
