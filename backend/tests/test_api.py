from __future__ import annotations

import httpx
import pytest
from app.main import app as industrial_app

from tractian_agent.agents.llm import LLMExecutionError
from tractian_agent.api.main import create_app
from tractian_agent.domain.models import AgentEvent, Modality, RunCreate
from tractian_agent.graph import AgentWorkflow
from tractian_agent.integrations.tractian import IndustrialClient
from tractian_agent.persistence import Database
from tractian_agent.services import RunService


@pytest.mark.asyncio
async def test_provider_failure_is_recorded_as_technical_failure_not_human_escalation(
    settings, monkeypatch
):
    database = Database(settings.app_database_path)
    database.initialize()
    industrial_transport = httpx.ASGITransport(app=industrial_app)
    workflow = AgentWorkflow(
        settings,
        client_factory=lambda user_id, seed: IndustrialClient(
            "http://industrial", user_id=user_id, seed=seed, transport=industrial_transport
        ),
    )
    service = RunService(settings, database, workflow)

    async def unavailable_classifier(*_args, **_kwargs):
        return (
            Modality.INVESTIGATE,
            "open_investigation",
            "",
            AgentEvent(
                role="classifier",
                model="gemini-test",
                status="failed",
                summary="O modelo não respondeu.",
                error="HTTP 503: temporarily unavailable",
            ),
        )

    monkeypatch.setattr(
        "tractian_agent.graph.workflow.classify_with_llm", unavailable_classifier
    )
    run = service.create(
        RunCreate(
            persona_id="lucas",
            asset_id="asset_B204",
            case_id="case_tkt_ctx_02",
            message="O que é BPFO e por que aparece no meu espectro?",
            seed="complete",
        )
    )

    with pytest.raises(LLMExecutionError):
        await service.execute(run["id"])

    saved = database.get_run(run["id"])
    assert saved is not None
    assert saved["status"] == "failed"
    assert saved["decision"] is None
    assert database.get_result(run["id"]) is None
    failed = database.list_checkpoints(run["id"])[-1]
    assert failed["node"] == "failed"
    assert failed["state"]["agent_events"][-1]["role"] == "classifier"
    assert failed["state"]["agent_events"][-1]["error"].startswith("HTTP 503")


@pytest.mark.asyncio
async def test_application_api_run_history_and_admin_checkpoints(settings):
    database = Database(settings.app_database_path)
    database.initialize()
    industrial_transport = httpx.ASGITransport(app=industrial_app)
    workflow = AgentWorkflow(
        settings,
        client_factory=lambda user_id, seed: IndustrialClient(
            "http://industrial", user_id=user_id, seed=seed, transport=industrial_transport
        ),
    )
    service = RunService(settings, database, workflow)
    app = create_app(settings, database, service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://application"
    ) as client:
        personas = (await client.get("/api/personas")).json()
        assert personas
        session = (
            await client.post("/api/sessions", json={"persona_id": "lucas"})
        ).json()
        response = await client.post(
            "/api/runs?wait=true",
            json={
                "persona_id": "lucas",
                "session_id": session["id"],
                "asset_id": "asset_B204",
                "case_id": "case_tkt_ctx_02",
                "message": "O que é BPFO e por que aparece no meu espectro?",
                "seed": "complete",
            },
        )
        assert response.status_code == 202
        run = response.json()
        result = await client.get(f"/api/runs/{run['id']}/result")
        checkpoints = await client.get(f"/api/admin/runs/{run['id']}/checkpoints")
        history = await client.get("/api/personas/lucas/history")
        events = await client.get(f"/api/runs/{run['id']}/events")
        assert result.status_code == 200
        checkpoint_payload = checkpoints.json()
        assert {item["node"] for item in checkpoint_payload} >= {
            "classifier",
            "source_plan",
            "source_collect",
            "source_select",
            "investigator",
            "sufficiency_gate",
            "reviewer",
            "writer",
            "finalize",
        }
        checkpoints_by_node = {item["node"]: item["state"] for item in checkpoint_payload}
        assert {item["role"] for item in checkpoints_by_node["classifier"]["agent_events"]} == {
            "classifier"
        }
        assert {item["role"] for item in checkpoints_by_node["reviewer"]["agent_events"]} == {
            "classifier",
            "source_selector",
            "investigator",
            "judge",
        }
        assert checkpoints_by_node["investigator"]["investigation"]["conclusion"]
        payload = result.json()
        assert {item["role"] for item in payload["agent_events"]} == {
            "classifier",
            "source_selector",
            "investigator",
            "judge",
            "writer",
        }
        assert payload["actions"] == []
        assert payload["metrics"]["mutations_attempted"] == 0
        assert history.json()[0]["id"] == run["id"]
        assert "event: progress" in events.text
        assert "event: done" in events.text
        assert '"state"' in events.text
        assert events.headers["cache-control"] == "no-cache"
        assert events.headers["x-accel-buffering"] == "no"

        repeated = await client.post(
            "/api/runs?wait=true",
            json={
                "persona_id": "lucas",
                "session_id": session["id"],
                "asset_id": "asset_B204",
                "case_id": "case_tkt_ctx_02",
                "investigation_key": "case_tkt_ctx_02",
                "message": "O que é BPFO e por que aparece no meu espectro?",
                "seed": "complete",
            },
        )
        assert repeated.json()["id"] == run["id"]
        assert repeated.json()["reused"] is True

        revised = await client.post(
            "/api/runs?wait=true",
            json={
                "persona_id": "lucas",
                "session_id": session["id"],
                "asset_id": "asset_B204",
                "case_id": "case_tkt_ctx_02",
                "investigation_key": "case_tkt_ctx_02",
                "message": "O que é BPFO e por que aparece no meu espectro?",
                "additional_context": "O técnico confirmou que o pico apareceu depois da manutenção.",
                "seed": "complete",
            },
        )
        revised_payload = revised.json()
        assert revised_payload["id"] != run["id"]
        assert revised_payload["revision"] == 2
        assert revised_payload["parent_run_id"] == run["id"]
        revised_result = (
            await client.get(f"/api/runs/{revised_payload['id']}/result")
        ).json()
        classifier = next(
            item for item in revised_result["agent_events"] if item["role"] == "classifier"
        )
        assert classifier["status"] != "reused"
