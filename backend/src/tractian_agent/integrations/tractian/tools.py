from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any
from uuid import uuid4

from tractian_agent.domain.models import QueryEnvelope, ToolError, ToolEvent

from .client import (
    IndustrialApiError,
    IndustrialClient,
    IndustrialResponseError,
    IndustrialTransportError,
)


class InstrumentedTools:
    """Fachada que torna cada uso da API um evento auditável."""

    def __init__(self, client: IndustrialClient) -> None:
        self.client = client

    async def read(
        self,
        name: str,
        path: str,
        arguments: dict[str, Any],
        operation: Callable[[], Awaitable[Any]],
    ) -> ToolEvent:
        return await self._call(name, "GET", path, arguments, operation)

    async def _call(
        self,
        name: str,
        method: str,
        path: str,
        arguments: dict[str, Any],
        operation: Callable[[], Awaitable[Any]],
    ) -> ToolEvent:
        started = perf_counter()
        event_id = f"tool_{uuid4().hex[:12]}"
        try:
            result = await operation()
            if isinstance(result, QueryEnvelope):
                return ToolEvent(
                    id=event_id,
                    name=name,
                    method=method,
                    path=path,
                    arguments=arguments,
                    envelope=result,
                    latency_ms=(perf_counter() - started) * 1000,
                )
            return ToolEvent(
                id=event_id,
                name=name,
                method=method,
                path=path,
                arguments=arguments,
                result=result,
                latency_ms=(perf_counter() - started) * 1000,
            )
        except IndustrialApiError as exc:
            error = ToolError(
                kind="http",
                status_code=exc.status_code,
                code=exc.code,
                message=exc.message,
                retryable=False,
            )
        except IndustrialTransportError as exc:
            error = ToolError(kind="transport", message=str(exc), retryable=exc.retryable)
        except IndustrialResponseError as exc:
            error = ToolError(kind="validation", message=str(exc), retryable=False)
        return ToolEvent(
            id=event_id,
            name=name,
            method=method,
            path=path,
            arguments=arguments,
            error=error,
            latency_ms=(perf_counter() - started) * 1000,
        )
