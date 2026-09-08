from __future__ import annotations

import inspect

import httpx
import pytest

from tractian_agent.integrations.tractian.client import IndustrialApiError, IndustrialClient

EXPECTED_OPERATIONS = {
    "get_company",
    "list_assets",
    "get_user",
    "get_asset",
    "list_analyses",
    "get_analysis",
    "get_baseline",
    "get_rms",
    "get_spectrum",
    "get_data_quality",
    "get_model",
    "search_knowledge",
    "get_knowledge",
}

FORBIDDEN_MUTATIONS = {
    "mutate",
    "update_asset",
    "reprocess",
    "request_specialist",
    "request_retraining",
    "escalate",
}


def test_client_exposes_read_operations_and_no_mutation_capability():
    assert all(inspect.iscoroutinefunction(getattr(IndustrialClient, name)) for name in EXPECTED_OPERATIONS)
    assert all(not hasattr(IndustrialClient, name) for name in FORBIDDEN_MUTATIONS)


@pytest.mark.asyncio
async def test_client_propagates_user_seed_and_preserves_envelope():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-user-id"] == "usr_test"
        assert request.url.params["seed"] == "stable"
        return httpx.Response(200, json={"mode": "conflict", "data": {"conflict": True}, "notes": "fontes divergentes"})

    client = IndustrialClient(
        "http://industrial",
        user_id="usr_test",
        seed="stable",
        transport=httpx.MockTransport(handler),
    )
    envelope = await client.get_asset("asset_1")
    await client.aclose()
    assert envelope.mode.value == "conflict"
    assert envelope.data == {"conflict": True}
    assert envelope.notes == "fontes divergentes"


@pytest.mark.asyncio
async def test_read_403_is_typed():
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, json={"code": "FORBIDDEN", "message": "sem permissão"})

    client = IndustrialClient(
        "http://industrial",
        user_id="usr_test",
        seed="complete",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(IndustrialApiError) as caught:
        await client.get_asset("asset_1")
    await client.aclose()
    assert caught.value.status_code == 403
    assert calls == 1
