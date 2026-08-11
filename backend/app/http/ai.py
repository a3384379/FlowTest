from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
from pydantic import JsonValue

from app.services.ai import AIProvider, AIProviderError, AIProviderResult


@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfiguration:
    base_url: str
    model: str
    api_key: str
    timeout_seconds: int


class OpenAICompatibleProvider(AIProvider):
    def __init__(self, configuration: OpenAICompatibleConfiguration) -> None:
        self._configuration = configuration

    async def generate(
        self,
        *,
        job_type: str,
        sanitized_input: dict[str, JsonValue],
        output_schema: dict[str, JsonValue],
    ) -> AIProviderResult:
        request = _chat_request(
            model=self._configuration.model,
            job_type=job_type,
            sanitized_input=sanitized_input,
            output_schema=output_schema,
        )
        try:
            async with httpx.AsyncClient(
                timeout=self._configuration.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{self._configuration.base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._configuration.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request,
                )
        except httpx.HTTPError as error:
            raise AIProviderError("AI_GATEWAY_UNAVAILABLE", "AI 网关暂时不可用") from error
        if response.status_code != 200:
            raise AIProviderError("AI_GATEWAY_REJECTED", "AI 网关拒绝了请求")
        return _provider_result(response)


def _chat_request(
    *,
    model: str,
    job_type: str,
    sanitized_input: dict[str, JsonValue],
    output_schema: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    return {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 FlowTest 的接口质量建议助手。只返回符合 JSON Schema 的建议。"
                    "不得请求、推断或输出 Secret。不得发布、执行或修改权限。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"job_type": job_type, "input": sanitized_input},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "flowtest_ai_suggestions",
                "strict": True,
                "schema": output_schema,
            },
        },
    }


def _provider_result(response: httpx.Response) -> AIProviderResult:
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        usage = body.get("usage", {})
        token_usage = {
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        }
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise AIProviderError("AI_RESPONSE_INVALID", "AI 网关返回格式无效") from error
    if not isinstance(parsed, dict):
        raise AIProviderError("AI_RESPONSE_INVALID", "AI 网关返回格式无效")
    return AIProviderResult(payload=parsed, token_usage=token_usage)
