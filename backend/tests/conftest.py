from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
API_SOURCE = ROOT / "api-tractian" / "api"
if str(API_SOURCE) not in sys.path:
    sys.path.insert(0, str(API_SOURCE))

from app.main import app as industrial_app

from tractian_agent.config import Settings
from tractian_agent.graph import AgentWorkflow
from tractian_agent.integrations.tractian import IndustrialClient


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_database_path=tmp_path / "agent.sqlite3",
        graph_checkpoint_path=tmp_path / "langgraph.sqlite3",
        industrial_api_url="http://industrial",
        default_seed="complete",
        llm_provider="custom",
        llm_base_url=None,
        llm_api_key=None,
        groq_api_key=None,
        llm_model=None,
    )


@pytest.fixture
def workflow(settings: Settings) -> AgentWorkflow:
    transport = httpx.ASGITransport(app=industrial_app)
    return AgentWorkflow(
        settings,
        client_factory=lambda user_id, seed: IndustrialClient(
            "http://industrial",
            user_id=user_id,
            seed=seed,
            transport=transport,
        ),
    )
