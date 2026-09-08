from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime
from enum import Enum
from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel

from tractian_agent.config import Settings
from tractian_agent.domain.models import AgentEvent

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_PROVIDER_ATTEMPTS = 3
_MAX_STRUCTURED_OUTPUT_TOKENS = 8192
_RATE_LIMIT_BUFFER_SECONDS = 0.5


class LLMExecutionError(RuntimeError):
    """Falha técnica de um agente LLM que não deve virar decisão de negócio."""

    def __init__(self, event: AgentEvent) -> None:
        self.event = event
        detail = event.error or "resposta estruturada inválida"
        super().__init__(
            f"O agente {event.role} não pôde usar o modelo {event.model}: {detail}"
        )


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in value
        )
    return str(value or "")


def _json_text(value: str) -> str:
    stripped = value.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    return fenced.group(1) if fenced else stripped


def _looks_truncated(content: str, finish_reason: object, exc: Exception) -> bool:
    reason = str(finish_reason or "").lower()
    message = str(exc).lower()
    stripped = _json_text(content).rstrip()
    return (
        reason in {"length", "max_tokens", "max_output_tokens"}
        or "eof while parsing" in message
        or (stripped.startswith("{") and not stripped.endswith("}"))
    )


def _expanded_token_budget(current: int) -> int:
    return min(max(current * 2, current + 1000), _MAX_STRUCTURED_OUTPUT_TOKENS)


def _provider_reports_truncation(response: httpx.Response) -> bool:
    if response.status_code not in {400, 422}:
        return False
    body = response.text.lower()
    return (
        "max completion tokens reached" in body
        or "maximum completion tokens reached" in body
        or "max_tokens" in body and "valid document" in body
    )


def _duration_seconds(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(ms|s)?", value.lower())
    if not match:
        return None
    duration = float(match.group(1))
    return duration / 1000 if match.group(2) == "ms" else duration


def _retry_delay_seconds(
    response: httpx.Response,
    attempt: int,
    max_wait_seconds: float,
) -> float:
    backoff = 0.4 * (2**attempt)
    if response.status_code != 429:
        return backoff
    candidates = [
        _duration_seconds(response.headers.get("retry-after")),
        _duration_seconds(response.headers.get("x-ratelimit-reset-tokens")),
    ]
    body_match = re.search(
        r"try again in\s+([0-9]+(?:\.[0-9]+)?\s*(?:ms|s)?)",
        response.text,
        flags=re.IGNORECASE,
    )
    candidates.append(_duration_seconds(body_match.group(1)) if body_match else None)
    provider_wait = max((value for value in candidates if value is not None), default=0)
    requested_wait = max(backoff, provider_wait + _RATE_LIMIT_BUFFER_SECONDS)
    return min(requested_wait, max_wait_seconds)


def _error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} retornado pelo provedor."
    return f"{type(exc).__name__}: {str(exc)[:300]}"


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Tipo não serializável: {type(value)!r}")


async def structured_call[SchemaT: BaseModel](
    settings: Settings,
    *,
    role: str,
    model: str | None,
    schema: type[SchemaT],
    system_prompt: str,
    payload: dict[str, Any],
    max_tokens: int,
) -> tuple[SchemaT | None, AgentEvent]:
    """Chamada OpenAI-compatible com JSON Schema e diagnóstico auditável."""
    started = perf_counter()
    api_key = settings.effective_llm_api_key
    if not (settings.llm_base_url and api_key and model):
        return None, AgentEvent(
            role=role,
            model=model or "offline",
            status="fallback",
            summary="Modelo não configurado; contingência local utilizada.",
            attempts=0,
            token_usage_complete=True,
            failure_stage="configuration",
            failure_reason="model_not_configured",
        )

    token_field = "max_completion_tokens" if settings.uses_groq else "max_tokens"
    request = {
        "model": model,
        "temperature": 0,
        token_field: max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": schema.model_json_schema(),
                # Os contratos Pydantic deste projeto possuem campos opcionais e mapas
                # abertos, que não pertencem ao subconjunto strict aceito pela Groq.
                # O modo best-effort ainda usa o schema; a validação final é feita abaixo.
                "strict": not settings.uses_groq,
            },
        },
        "messages": [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n\n"
                    "Responda exclusivamente com um objeto JSON válido, sem Markdown."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, default=_json_default),
            },
        ],
    }
    if settings.uses_groq and "gpt-oss" in model.lower():
        request["reasoning_effort"] = (
            "low" if role in {"classifier", "source_selector", "writer"} else "medium"
        )
        request["include_reasoning"] = False
    # Qwen 3.8 usa thinking xhigh por padrão. Em saídas estruturadas curtas isso pode
    # consumir todo o limite antes de produzir `message.content`.
    if "qwen3.8" in model.lower():
        request["chat_template_kwargs"] = {
            "enable_thinking": False,
            "preserve_thinking": False,
        }
    attempts = 0
    usage_responses = 0
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    last_failure_stage = "provider"
    last_failure_reason = "provider_error"

    def observe_usage(payload_json: dict[str, Any]) -> None:
        nonlocal usage_responses, prompt_tokens, completion_tokens, total_tokens
        usage = payload_json.get("usage")
        if not isinstance(usage, dict):
            return
        usage_responses += 1
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        total_tokens += int(usage.get("total_tokens") or 0)

    try:
        async with httpx.AsyncClient(
            base_url=str(settings.llm_base_url).rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=settings.llm_timeout_seconds,
        ) as client:
            for attempt in range(_MAX_PROVIDER_ATTEMPTS):
                try:
                    attempts += 1
                    response = await client.post("/chat/completions", json=request)
                    if _provider_reports_truncation(response):
                        current_budget = int(request[token_field])
                        expanded_budget = _expanded_token_budget(current_budget)
                        if (
                            attempt == _MAX_PROVIDER_ATTEMPTS - 1
                            or expanded_budget == current_budget
                        ):
                            response.raise_for_status()
                        request[token_field] = expanded_budget
                        await asyncio.sleep(0.4 * (2**attempt))
                        continue
                    # Alguns provedores OpenAI-compatible aceitam JSON, mas não JSON Schema.
                    if response.status_code in {400, 405, 415, 422}:
                        request["response_format"] = {"type": "json_object"}
                        request["messages"][0]["content"] = (
                            f"{system_prompt}\n\n"
                            "Responda exclusivamente com um objeto JSON válido, sem Markdown, "
                            "seguindo este JSON Schema: "
                            f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
                        )
                        attempts += 1
                        response = await client.post("/chat/completions", json=request)
                        if _provider_reports_truncation(response):
                            current_budget = int(request[token_field])
                            expanded_budget = _expanded_token_budget(current_budget)
                            if (
                                attempt == _MAX_PROVIDER_ATTEMPTS - 1
                                or expanded_budget == current_budget
                            ):
                                response.raise_for_status()
                            request[token_field] = expanded_budget
                            await asyncio.sleep(0.4 * (2**attempt))
                            continue
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if (
                        exc.response.status_code not in _RETRYABLE_STATUS_CODES
                        or attempt == _MAX_PROVIDER_ATTEMPTS - 1
                    ):
                        raise
                    await asyncio.sleep(
                        _retry_delay_seconds(
                            exc.response,
                            attempt,
                            settings.llm_max_rate_limit_wait_seconds,
                        )
                    )
                    continue
                except httpx.ConnectError:
                    if attempt == _MAX_PROVIDER_ATTEMPTS - 1:
                        raise
                    await asyncio.sleep(0.4 * (2**attempt))
                    continue
                except httpx.TimeoutException:
                    # Um timeout pode ser transitório, mas repetir três janelas completas
                    # deixaria a interface parada por tempo excessivo.
                    if attempt >= 1:
                        raise
                    await asyncio.sleep(0.4)
                    continue

                payload_json = response.json()
                observe_usage(payload_json)
                choice = payload_json["choices"][0]
                content = _content_text(choice["message"]["content"])
                try:
                    parsed = schema.model_validate_json(_json_text(content))
                except (TypeError, ValueError) as exc:
                    try:
                        json.loads(_json_text(content))
                    except (TypeError, ValueError):
                        last_failure_stage = "json"
                        last_failure_reason = "invalid_json"
                    else:
                        last_failure_stage = "schema"
                        last_failure_reason = "schema_validation_failed"
                    truncated = _looks_truncated(content, choice.get("finish_reason"), exc)
                    current_budget = int(request[token_field])
                    expanded_budget = _expanded_token_budget(current_budget)
                    if (
                        not truncated
                        or attempt == _MAX_PROVIDER_ATTEMPTS - 1
                        or expanded_budget == current_budget
                    ):
                        raise
                    request[token_field] = expanded_budget
                    await asyncio.sleep(0.4 * (2**attempt))
                    continue
                return parsed, AgentEvent(
                    role=role,
                    model=model,
                    status="completed",
                    latency_ms=(perf_counter() - started) * 1000,
                    summary=f"Saída estruturada {schema.__name__} validada.",
                    prompt_tokens=prompt_tokens if usage_responses else None,
                    completion_tokens=completion_tokens if usage_responses else None,
                    total_tokens=total_tokens if usage_responses else None,
                    attempts=attempts,
                    token_usage_complete=usage_responses == attempts,
                )
            raise ValueError("O provedor esgotou as tentativas sem uma saída completa.")
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        return None, AgentEvent(
            role=role,
            model=model,
            status="failed",
            latency_ms=(perf_counter() - started) * 1000,
            summary="O modelo não produziu uma saída estruturada utilizável.",
            error=_error_text(exc),
            prompt_tokens=prompt_tokens if usage_responses else None,
            completion_tokens=completion_tokens if usage_responses else None,
            total_tokens=total_tokens if usage_responses else None,
            attempts=attempts,
            token_usage_complete=usage_responses == attempts,
            failure_stage=last_failure_stage,
            failure_reason=last_failure_reason,
        )
