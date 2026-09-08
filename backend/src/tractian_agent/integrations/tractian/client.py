from __future__ import annotations

from typing import Any, Self

import httpx
from pydantic import ValidationError

from tractian_agent.domain.models import QueryEnvelope


class IndustrialClientError(RuntimeError):
    """Base para erros tipados da API industrial."""


class IndustrialApiError(IndustrialClientError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class IndustrialTransportError(IndustrialClientError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class IndustrialResponseError(IndustrialClientError):
    pass


class IndustrialClient:
    """Cliente industrial deliberadamente somente-leitura."""

    def __init__(
        self,
        base_url: str,
        *,
        user_id: str,
        seed: str,
        timeout: float = 8.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.user_id = user_id
        self.seed = seed
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"x-user-id": user_id},
            timeout=httpx.Timeout(timeout),
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def read(self, path: str, params: dict[str, Any] | None = None) -> QueryEnvelope:
        query = {"seed": self.seed, **(params or {})}
        payload = await self._request("GET", path, params=query)
        try:
            return QueryEnvelope.model_validate(payload)
        except ValidationError as exc:
            raise IndustrialResponseError(f"Envelope inválido em GET {path}: {exc}") from exc

    async def get_user(self) -> dict[str, Any]:
        return await self._request("GET", "/users/me")

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise IndustrialTransportError(f"Falha de transporte em {method} {path}: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise IndustrialResponseError(
                f"Resposta não JSON em {method} {path} ({response.status_code})."
            ) from exc
        if response.is_error:
            raise IndustrialApiError(
                response.status_code,
                str(payload.get("code", "ERROR")),
                str(payload.get("message", payload)),
            )
        if not isinstance(payload, dict):
            raise IndustrialResponseError(f"Objeto JSON esperado em {method} {path}.")
        return payload

    # Contexto
    async def get_company(self, company_id: str) -> QueryEnvelope:
        return await self.read(f"/companies/{company_id}")

    async def list_assets(self, company_id: str) -> QueryEnvelope:
        return await self.read(f"/companies/{company_id}/assets")

    async def get_asset(self, asset_id: str) -> QueryEnvelope:
        return await self.read(f"/assets/{asset_id}")

    # Análises e dados técnicos
    async def list_analyses(self, asset_id: str, status: str | None = None) -> QueryEnvelope:
        if status not in {None, "current", "stale", "pending", "inconclusive"}:
            raise ValueError(f"Filtro de análise não suportado: {status!r}")
        return await self.read(
            f"/assets/{asset_id}/analyses", {"status": status} if status else None
        )

    async def get_analysis(self, analysis_id: str) -> QueryEnvelope:
        return await self.read(f"/analyses/{analysis_id}")

    async def get_baseline(self, asset_id: str) -> QueryEnvelope:
        return await self.read(f"/assets/{asset_id}/baseline")

    async def get_rms(self, asset_id: str) -> QueryEnvelope:
        return await self.read(f"/assets/{asset_id}/rms")

    async def get_spectrum(self, asset_id: str) -> QueryEnvelope:
        return await self.read(f"/assets/{asset_id}/spectrum")

    async def get_data_quality(self, asset_id: str) -> QueryEnvelope:
        return await self.read(f"/assets/{asset_id}/data-quality")

    async def get_model(self, model_id: str) -> QueryEnvelope:
        return await self.read(f"/models/{model_id}")

    async def search_knowledge(self, query: str, type_: str | None = None) -> QueryEnvelope:
        params = {"q": query}
        if type_:
            params["type"] = type_
        return await self.read("/knowledge/search", params)

    async def get_knowledge(self, document_id: str) -> QueryEnvelope:
        return await self.read(f"/knowledge/{document_id}")
